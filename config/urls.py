from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from accounts.views import admin_dashboard, export_parcel_report
from accounts.analytics import courier_analytics
from complaints.views import (
    agent_complaints,
    complaint_admin_list,
    complaint_create,
    complaint_detail,
    my_complaints,
)
from parcels.views import (
    agent_parcels,
    customer_parcels,
    parcel_create,
    parcel_list,
    parcel_track,
    shipping_label,
)

urlpatterns = [
    path("track/", parcel_track, name="public_parcel_track"),
    path("admin/dashboard/", admin_dashboard, name="admin_dashboard"),
    path("admin/analytics/", courier_analytics, name="courier_analytics"),
    path("admin/parcels/", parcel_list, name="admin_parcels"),
    path("admin/parcels/new/", parcel_create, name="admin_parcel_create"),
    path("admin/parcels/export-csv/", export_parcel_report, name="admin_parcel_export"),
    path("admin/parcels/<str:tracking_id>/label/", shipping_label, name="admin_parcel_label"),
    path("admin/complaints/", complaint_admin_list, name="admin_complaints"),
    path("agent/deliveries/", agent_parcels, name="agent_deliveries"),
    path("agent/complaints/", agent_complaints, name="agent_assigned_complaints"),
    path("agent/complaints/<int:complaint_id>/", complaint_detail, name="agent_complaint_detail"),
    path("customer/parcels/", customer_parcels, name="customer_shipments"),
    path("customer/complaints/", my_complaints, name="customer_complaints"),
    path("customer/complaints/new/", complaint_create, name="customer_complaint_create"),
    path("customer/complaints/<int:complaint_id>/", complaint_detail, name="customer_complaint_detail"),
    path("admin/", admin.site.urls),
    path("parcels/", include("parcels.urls")),
    path("", include("accounts.urls")),
    path("complaints/", include("complaints.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
