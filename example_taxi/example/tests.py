from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group as AuthGroup
from rest_framework.authtoken.models import Token
from rest_framework.reverse import reverse
from rest_framework.status import HTTP_201_CREATED, HTTP_200_OK, \
    HTTP_204_NO_CONTENT
from rest_framework.test import APIClient, APITestCase
from channels import Group
from channels.test import ChannelTestCase, HttpClient

from .serializers import PublicUserSerializer, PrivateUserSerializer, \
    TripSerializer
from .models import Trip

PASSWORD = 'pAssw0rd!'


def create_user(username='user@example.com', password=PASSWORD, group='rider'):
    auth_group, _ = AuthGroup.objects.get_or_create(name=group)
    user = get_user_model().objects.create_user(
        username=username, password=password)
    user.groups.add(auth_group)
    user.save()
    return user


class AuthenticationTest(APITestCase):

    def setUp(self):
        self.client = APIClient()

    def test_user_can_sign_up(self):
        response = self.client.post(reverse('sign_up'), data={
            'username': 'user@example.com',
            'password1': PASSWORD,
            'password2': PASSWORD
        })
        user = get_user_model().objects.last()
        self.assertEqual(HTTP_201_CREATED, response.status_code)
        self.assertEqual(PublicUserSerializer(user).data, response.data)

    def test_user_can_log_in(self):
        user = create_user()
        response = self.client.post(reverse('log_in'), data={
            'username': user.username,
            'password': PASSWORD,
        })
        self.assertEqual(HTTP_200_OK, response.status_code)
        self.assertEqual(PrivateUserSerializer(user).data, response.data)
        self.assertIsNotNone(Token.objects.get(user=user))

    def test_user_can_log_out(self):
        user = create_user()
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        self.client.login(username=user.username, password=PASSWORD)
        response = self.client.post(reverse('log_out'))
        self.assertEqual(HTTP_204_NO_CONTENT, response.status_code)
        self.assertFalse(Token.objects.filter(user=user).exists())


class HttpTripTest(APITestCase):
    def setUp(self):
        self.user = create_user()
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token}')

    def test_user_can_list_personal_trips(self):
        trips = [
            Trip.objects.create(
                pick_up_address='A', drop_off_address='B', rider=self.user),
            Trip.objects.create(
                pick_up_address='B', drop_off_address='C', rider=self.user),
            Trip.objects.create(
                pick_up_address='C', drop_off_address='D')
        ]
        response = self.client.get(reverse('trip:trip_list'))
        self.assertEqual(HTTP_200_OK, response.status_code)
        self.assertEqual(
            TripSerializer(trips[0:2], many=True).data, response.data)

    def test_user_can_retrieve_personal_trip_by_nk(self):
        trip = Trip.objects.create(
            pick_up_address='A', drop_off_address='B', rider=self.user)
        response = self.client.get(trip.get_absolute_url())
        self.assertEqual(HTTP_200_OK, response.status_code)
        self.assertEqual(TripSerializer(trip).data, response.data)


class WebSocketTripTest(ChannelTestCase):
    def setUp(self):
        self.driver = create_user(
            username='driver@example.com', group='driver')
        self.rider = create_user(username='rider@example.com', group='rider')

    def connect_as_driver(self, driver):
        client = HttpClient()
        client.login(username=driver.username, password=PASSWORD)
        client.send_and_consume('websocket.connect', path='/driver/')
        return client

    def connect_as_rider(self, rider):
        client = HttpClient()
        client.login(username=rider.username, password=PASSWORD)
        client.send_and_consume('websocket.connect', path='/rider/')
        return client

    def test_driver_can_connect_via_websockets(self):
        client = self.connect_as_driver(self.driver)
        message = client.receive()
        self.assertIsNone(message)

    def test_rider_can_connect_via_websockets(self):
        client = self.connect_as_rider(self.rider)
        message = client.receive()
        self.assertIsNone(message)

    def create_trip(self, rider, pick_up_address='A', drop_off_address='B'):
        client = self.connect_as_rider(rider)
        client.send_and_consume('websocket.receive', path='/rider/', content={
            'text': {
                'pick_up_address': pick_up_address,
                'drop_off_address': drop_off_address,
                'rider': PublicUserSerializer(rider).data
            }
        })
        return client

    def test_rider_can_create_trips(self):
        client = self.create_trip(self.rider)
        message = client.receive()
        trip = Trip.objects.last()
        self.assertEqual(TripSerializer(trip).data, message)

    def test_rider_is_subscribed_to_trip_channel_on_creation(self):
        client = self.create_trip(self.rider)
        client.receive()
        trip = Trip.objects.last()

        # Subsequent messages sent to the same channel are received
        # by the client.
        message = {'detail': 'This is a test message.'}
        Group(trip.nk).send(message)
        self.assertEqual(message, client.receive())

    def update_trip(self, driver, trip, status):
        client = self.connect_as_driver(driver)
        client.send_and_consume('websocket.receive', path='/driver/', content={
            'text': {
                'nk': trip.nk,
                'pick_up_address': trip.pick_up_address,
                'drop_off_address': trip.drop_off_address,
                'status': status,
                'driver': PublicUserSerializer(driver).data
            }
        })
        return client

    def test_driver_can_update_trips(self):
        trip = Trip.objects.create(pick_up_address='A', drop_off_address='B')
        client = self.update_trip(self.driver, trip=trip, status=Trip.STARTED)
        trip = Trip.objects.get(nk=trip.nk)
        self.assertEqual(TripSerializer(trip).data, client.receive())

    def test_driver_is_subscribed_to_trip_channel_on_update(self):
        trip = Trip.objects.create(pick_up_address='A', drop_off_address='B')
        client = self.update_trip(self.driver, trip=trip, status=Trip.STARTED)
        client.receive()
        trip = Trip.objects.last()
        message = {'detail': 'This is a test message.'}
        Group(trip.nk).send(message)
        self.assertEqual(message, client.receive())

    def test_driver_is_alerted_on_trip_creation(self):
        client = self.connect_as_driver(self.driver)
        self.create_trip(self.rider)
        trip = Trip.objects.last()
        self.assertEqual(TripSerializer(trip).data, client.receive())

    def test_rider_is_alerted_on_trip_update(self):
        client = self.create_trip(self.rider)
        client.receive()
        trip = Trip.objects.last()
        self.update_trip(self.driver, trip=trip, status=Trip.STARTED)
        trip = Trip.objects.get(nk=trip.nk)
        self.assertEqual(TripSerializer(trip).data, client.receive())
