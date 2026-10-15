from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("parcels/", include("parcels.urls")),
    path("", include("accounts.urls")),
    path("complaints/", include("complaints.urls")),
    
]