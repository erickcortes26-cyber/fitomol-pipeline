from django.contrib import admin
from django.urls import path, include
from . import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='index'),
    path("listar_historias/", views.listar_historias, name="listar_historias"),
    path('crear_historia/', views.crear_historia, name="crear_historia"),
    path("subir_archivo/", views.subir_archivo, name="subir_archivo"),
    path('ejecutar_workflow/', views.ejecutar_workflow, name='ejecutar_workflow'),
    path('show_dataset/<str:id>/', views.show_dataset, name='show_dataset'),
    path('get_jobs/<str:id>', views.get_jobs, name="get_jobs"),
    path('get_jobs_history/<str:id>', views.get_jobs_history, name="get_jobs_history"),
    path('pipeline_progress_view/', views.pipeline_progress_view, name='pipeline_progress_view'),
    path('pipeline_progress/', views.pipeline_progress, name='pipeline_progress'),
    path("user/", include('user_app.urls')),
    path("ejecutar_augustus_view/", views.ejecutar_augustus, name="ejecutar_augustus_view"),

    # URLS Para desarrollo
    path("get_inputs_job/<path:id>/", views.get_inputs_job, name="get_inputs_job"),
    path("get_outputs_job/<path:id>/", views.get_outputs_job, name="get_outputs_job"),
    path("ejecutar_trimmomatic_single/<str:history_id>", views.ejecutar_trimmomatic_single, name="ejecutar_trimmomatic_single"),
    path("ver_parametros_permitidos_tool/<path:id_tool>", views.ver_parametros_permitidos_tool, name="ver_parametros_permitidos_tool")
]
