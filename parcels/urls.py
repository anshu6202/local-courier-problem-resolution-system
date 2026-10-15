from django.urls import path
from . import views

urlpatterns = [
    path("", views.parcel_list, name="parcel_list"),
    path("new/", views.parcel_create, name="parcel_create"),
    path("track/", views.parcel_track, name="parcel_track"),
    path("my-deliveries/",views.agent_parcels,name="agent_parcels",),
    path("update-status/<str:tracking_id>/",views.update_parcel_status,name="update_parcel_status",),
]