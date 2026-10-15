from django.urls import path
from django.contrib.auth.views import LogoutView
from .views import UserLoginView, dashboard
from . import views

urlpatterns = [
    path("login/", UserLoginView.as_view(), name="login"),
    path("dashboard/", dashboard, name="dashboard"),
    path("logout/",LogoutView.as_view(),name="logout",),
    path("", dashboard, name="dashboard"),
    path("reports/parcels/export/",views.export_parcel_report,name="export_parcel_report",),
]
