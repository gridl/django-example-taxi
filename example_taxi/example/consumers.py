from channels import Group
from channels.generic.websockets import JsonWebsocketConsumer
from .models import Trip
from .serializers import TripSerializer


class TripConsumer(JsonWebsocketConsumer):
    http_user = True

    def user_trip_nks(self):
        raise NotImplementedError()

    def connect(self, message, **kwargs):
        self.message.reply_channel.send({'accept': True})
        if self.message.user.is_authenticated:
            # Get the trips associated with the user (as a driver or a rider).
            # Add the list of trip NKs to the user's channel session data.
            trip_nks = list(self.user_trip_nks())
            self.message.channel_session['trip_nks'] = trip_nks

            # Add the user's reply channel to each trip group.
            for trip_nk in trip_nks:
                Group(trip_nk).add(self.message.reply_channel)

    def disconnect(self, message, **kwargs):
        # Remove the user's reply channel from each associated trip group.
        if 'trip_nks' in message.channel_session:
            for trip_nk in message.channel_session['trip_nks']:
                Group(trip_nk).discard(message.reply_channel)


class DriverConsumer(TripConsumer):
    groups = ['drivers']

    def user_trip_nks(self):
        return self.message.user.trips_as_driver.exclude(
            status=Trip.COMPLETED).only('nk').values_list('nk', flat=True)

    def connect(self, message, **kwargs):
        super().connect(message, **kwargs)

        # Add all drivers to a special group.
        Group('drivers').add(self.message.reply_channel)

    def receive(self, content, **kwargs):
        # Find an existing trip by its NK.
        trip = Trip.objects.get(nk=content.get('nk'))

        # Update the trip using the request data.
        serializer = TripSerializer(data=content)
        serializer.is_valid(raise_exception=True)
        trip = serializer.update(trip, serializer.validated_data)

        # Add the trip NK to the driver's channel session.
        self.message.channel_session['trip_nks'].append(trip.nk)

        # Add the user's reply channel to the trip group.
        Group(trip.nk).add(self.message.reply_channel)

        # Send the serialized trip data to everyone in the trip group.
        trips_data = TripSerializer(trip).data
        self.group_send(name=trip.nk, content=trips_data)


class RiderConsumer(TripConsumer):
    def user_trip_nks(self):
        # Find all active trips for the rider.
        return self.message.user.trips_as_rider.exclude(
            status=Trip.COMPLETED).only('nk').values_list('nk', flat=True)

    def receive(self, content, **kwargs):
        # Create a trip using the data passed in the request.
        serializer = TripSerializer(data=content)
        serializer.is_valid(raise_exception=True)
        trip = serializer.create(serializer.validated_data)

        # Add the new trip NK to the rider's channel session.
        self.message.channel_session['trip_nks'].append(trip.nk)

        # Add the user's reply channel to the new trip group.
        Group(trip.nk).add(self.message.reply_channel)

        # Send the serialized trip data to everyone in the trip group.
        trips_data = TripSerializer(trip).data
        self.group_send(name=trip.nk, content=trips_data)

        # Send trip request to all drivers.
        self.group_send(name='drivers', content=trips_data)
