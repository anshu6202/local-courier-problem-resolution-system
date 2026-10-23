from django.urls import path
from . import views

urlpatterns = [
    path("", views.parcel_list, name="parcel_list"),
    path("new/", views.parcel_create, name="parcel_create"),
    path("track/", views.parcel_track, name="parcel_track"),
    path("book/", views.customer_parcel_booking, name="customer_parcel_booking"),
    path("mine/<str:tracking_id>/redelivery/", views.customer_redelivery_request, name="customer_redelivery_request"),
    path("redelivery-requests/", views.admin_redelivery_requests, name="admin_redelivery_requests"),
    path("<str:tracking_id>/label/", views.shipping_label, name="parcel_shipping_label"),
    path("mine/", views.customer_parcels, name="customer_parcels"),
    path("my-deliveries/",views.agent_parcels,name="agent_parcels",),
    path("update-status/<str:tracking_id>/",views.update_parcel_status,name="update_parcel_status",),
]
