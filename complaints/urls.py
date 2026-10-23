from django.urls import path
from . import views

urlpatterns = [
    path("admin/notifications/", views.admin_complaint_notifications, name="admin_complaint_notifications"),
    path("admin/notifications/<int:notification_id>/read/", views.mark_complaint_notification_read, name="mark_complaint_notification_read"),
    path("new/", views.complaint_create, name="complaint_create"),
    path("my/", views.my_complaints, name="my_complaints"),
    path("<int:complaint_id>/", views.complaint_detail, name="complaint_detail"),
    path("manage/", views.complaint_admin_list, name="complaint_admin_list"),
    path("admin/", views.complaint_admin_list, name="complaint_admin_list"),
    path("agent/",views.agent_complaints,name="agent_complaints",),
    path("resolve/<int:complaint_id>/",views.resolve_complaint,name="resolve_complaint",),
]
