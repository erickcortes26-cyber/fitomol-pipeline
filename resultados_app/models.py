from django.db import models
from django.contrib.auth.models import User

class ResultadoPipeline(models.Model):
    # Info general
    usuario         = models.CharField(max_length=150)
    nombre_historia = models.CharField(max_length=255)
    history_id      = models.CharField(max_length=100)
    fecha           = models.DateTimeField(auto_now_add=True)

    # Ganador QUAST
    ganador         = models.CharField(max_length=20, choices=[('spades','SPAdes'),('velvet','Velvet')], null=True, blank=True)

    # Métricas QUAST SPAdes
    n50_spades      = models.FloatField(null=True, blank=True)
    l50_spades      = models.FloatField(null=True, blank=True)

    # Métricas QUAST Velvet
    n50_velvet      = models.FloatField(null=True, blank=True)
    l50_velvet      = models.FloatField(null=True, blank=True)

    # Duración total en segundos
    duracion_total  = models.IntegerField(null=True, blank=True)

    # Reportes HTML descargados de Galaxy
    reporte_fastqc_r1_inicial  = models.FileField(upload_to='reportes/fastqc/', null=True, blank=True)
    reporte_fastqc_r2_inicial  = models.FileField(upload_to='reportes/fastqc/', null=True, blank=True)
    reporte_fastqc_r1_final    = models.FileField(upload_to='reportes/fastqc/', null=True, blank=True)
    reporte_fastqc_r2_final    = models.FileField(upload_to='reportes/fastqc/', null=True, blank=True)
    reporte_quast_spades       = models.FileField(upload_to='reportes/quast/', null=True, blank=True)
    reporte_quast_velvet       = models.FileField(upload_to='reportes/quast/', null=True, blank=True)

    class Meta:
        app_label = 'resultados_app'
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.nombre_historia} — {self.fecha.strftime('%Y-%m-%d %H:%M')}"
