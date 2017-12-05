from django.conf.urls import include, url
from django.contrib import admin

from example.apis import SignUpView, LogInView, LogOutView

urlpatterns = [
    url(r'^admin/', admin.site.urls),
    url(r'^api/sign_up/$', SignUpView.as_view(), name='sign_up'),
    url(r'^api/log_in/$', LogInView.as_view(), name='log_in'),
    url(r'^api/log_out/$', LogOutView.as_view(), name='log_out'),
    url(r'^api/trip/', include('example.urls', namespace='trip')),
]
