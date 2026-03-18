class ResultadosRouter:
    """
    Enruta todos los modelos de resultados_app a la base de datos PostgreSQL.
    El resto va a SQLite (default).
    """
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'resultados_app':
            return 'resultados'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'resultados_app':
            return 'resultados'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._meta.app_label == 'resultados_app' or obj2._meta.app_label == 'resultados_app':
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == 'resultados_app':
            return db == 'resultados'
        return db == 'default'
