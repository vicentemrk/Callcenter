from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.validators import MaxLengthValidator
from online.constants import CATEGORIAS_PREGUNTA
from online.validators import validar_rut_chileno

class UserManager(BaseUserManager):
    def create_user(self, correo, usuario, password=None, **extra_fields):
        """
        Crea y guarda un usuario con el correo, usuario y password dados.
        """
        if not correo:
            raise ValueError('El usuario debe tener un correo electrónico')
        if not usuario:
            raise ValueError('El usuario debe tener un nombre de usuario')

        user = self.model(
            correo=self.normalize_email(correo),
            usuario=usuario,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, correo, usuario, password=None, **extra_fields):
        """
        Crea y guarda un superusuario con el correo, usuario y password dados.
        """
        extra_fields.setdefault('rol', 'administrador')
        extra_fields.setdefault('activo', True)

        if extra_fields.get('rol') != 'administrador':
            raise ValueError('Superuser debe tener rol=administrador.')

        return self.create_user(correo, usuario, password, **extra_fields)

class Usuario(AbstractBaseUser):
    nombre = models.CharField(
        verbose_name='Nombre',
        max_length=30,
        blank=True,
        null=True
    )
    apellido = models.CharField(
        verbose_name='Apellido',
        max_length=30,
        blank=True,
        null=True
    )
    rut = models.CharField(
        verbose_name='RUT',
        max_length=12,
        unique=True,
        blank=True,
        null=True,
        validators=[validar_rut_chileno],
    )
    correo = models.EmailField(
        verbose_name='Correo electrónico',
        max_length=70,
        unique=True,
    )
    usuario = models.CharField(
        verbose_name='Usuario',
        max_length=50,
        unique=True,
    )
    fecha_nacimiento = models.DateField(
        verbose_name='Fecha de nacimiento',
        null=True,
        blank=True
    )
    activo = models.BooleanField(default=True)
    ROLES = [
        ('cliente', 'Cliente'),
        ('tecnico', 'Técnico'),
        ('administrador', 'Administrador'),
    ]
    rol = models.CharField(
        max_length=20,
        choices=ROLES,
        default='cliente',
        db_index=True,
    )

    USERNAME_FIELD = 'usuario'
    REQUIRED_FIELDS = ['correo']

    objects = UserManager()

    def get_full_name(self):
        return f"{self.nombre} {self.apellido}"

    def get_short_name(self):
        return self.usuario

    def has_perm(self, perm, obj=None):
        return self.is_active and self.rol == 'administrador'

    def has_module_perms(self, app_label):
        return self.is_active and self.rol == 'administrador'

    @property
    def is_active(self):
        return self.activo

    @property
    def is_staff(self):
        return self.rol == 'administrador'

    @property
    def is_admin(self):
        return self.rol == 'administrador'

    @property
    def admin(self):
        return self.rol == 'administrador'

    @admin.setter
    def admin(self, value):
        if value:
            self.rol = 'administrador'
        elif self.rol == 'administrador':
            self.rol = 'cliente'

    @property
    def tecnico(self):
        return self.rol == 'tecnico'

    @tecnico.setter
    def tecnico(self, value):
        if value and self.rol != 'administrador':
            self.rol = 'tecnico'
        elif not value and self.rol == 'tecnico':
            self.rol = 'cliente'

    def __init__(self, *args, **kwargs):
        admin = kwargs.pop('admin', None)
        tecnico = kwargs.pop('tecnico', None)
        super().__init__(*args, **kwargs)
        if admin is True:
            self.rol = 'administrador'
        elif tecnico is True and self.rol == 'cliente':
            self.rol = 'tecnico'

    def __str__(self):
        return self.usuario

class Preguntas(models.Model):
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('en_proceso', 'En proceso'),
        ('resuelto', 'Resuelto'),
        ('cerrado', 'Cerrado'),
    ]
    PRIORIDADES = [
        ('baja', 'Baja'),
        ('media', 'Media'),
        ('alta', 'Alta'),
        ('urgente', 'Urgente'),
    ]

    idPregunta = models.AutoField(primary_key=True)
    Titulo = models.CharField(max_length=60)
    Pregunta = models.TextField(
        max_length=750,
        validators=[MaxLengthValidator(750)],
    )
    Fecha_creacion = models.DateTimeField()
    categoria = models.CharField(
        max_length=20,
        choices=CATEGORIAS_PREGUNTA,
        default='otros',
        db_index=True
    )
    Usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    estado = models.CharField(
        max_length=20,
        choices=ESTADOS,
        default='en_proceso',
        db_index=True,
    )
    prioridad = models.CharField(
        max_length=10,
        choices=PRIORIDADES,
        default='baja',
        db_index=True,
    )

    def __str__(self):
        return f"{self.idPregunta} - {self.Titulo}"

class Respuesta(models.Model):
    idRespuesta = models.AutoField(primary_key=True)
    Respuesta = models.TextField(
        verbose_name='Respuesta',
        max_length=750,
        validators=[MaxLengthValidator(750)],
    )
    id_Pregunta = models.ForeignKey(Preguntas, on_delete=models.CASCADE)
    Usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    FechaHora = models.DateTimeField()

    def __str__(self):
        return f"{self.idRespuesta} - {self.Respuesta[:20]}"

class Auditoria(models.Model):
    ACCIONES = [
        ('crear_pregunta', 'Crear pregunta'),
        ('modificar_pregunta', 'Modificar pregunta'),
        ('cambiar_estado', 'Cambiar estado'),
        ('cambiar_prioridad', 'Cambiar prioridad'),
        ('eliminar_pregunta', 'Eliminar pregunta'),
        ('modificar_usuario', 'Modificar usuario'),
        ('eliminar_usuario', 'Eliminar usuario'),
    ]

    usuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    pregunta = models.ForeignKey(
        Preguntas,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    accion = models.CharField(max_length=30, choices=ACCIONES)
    detalle = models.CharField(max_length=255, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.accion} - {self.fecha:%Y-%m-%d %H:%M}"
