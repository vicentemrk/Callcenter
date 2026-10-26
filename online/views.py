from django.shortcuts import render, redirect
from django.contrib.auth import logout
from django.utils import timezone
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from online.forms import RegisterForm, LoginForm, PreguntasForm, RespuestaForm
from django.views.generic import CreateView, FormView
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from online.models import Preguntas, Usuario, Respuesta
from online.ia_utils import AsistenteIA
from online.recomendaciones_ia import RecomendadorIA


def _redirigir_por_rol(usuario):
    """Manda a cada rol a su pantalla de inicio."""
    if usuario.rol in ('administrador', 'tecnico'):
        return redirect('administracion')
    return redirect('inicio', id=usuario.id)


# Vista para la página principal
def Index(request):
    """
    Página principal del sitio
    """
    if request.user.is_authenticated:
        return _redirigir_por_rol(request.user)
    return render(request, "index.html")

# Vista para logout personalizada
@require_POST
def logout_view(request):
    """
    Vista personalizada para logout
    """
    logout(request)
    return redirect('Login')

# Vista de inicio de usuario
@login_required
def Inicio(request, id):
    """
    Vista del panel de usuario
    """
    if request.user.rol != 'cliente':
        return _redirigir_por_rol(request.user)
    try:
        usuario = Usuario.objects.get(id=id)
        if request.user.id != usuario.id:
            return redirect('inicio', id=request.user.id)
        preguntas = Preguntas.objects.filter(Usuario=usuario)
        now = timezone.now()
        form = PreguntasForm(initial={'Usuario': id, 'Fecha_creacion': now})
        sugerencias_ia = None
        """
        Conectamos los asistentes de IA para generar respuestas automáticas y recomendaciones basadas en la pregunta del usuario.Qu
        """
        consulta = request.GET.get("buscar_ayuda", "").strip()[:250]
        if consulta:
            asistente = AsistenteIA(usuario=request.user)
            recomendador = RecomendadorIA()
            sugerencias_ia = {
                "consulta_original": consulta,
                "respuesta_automatica": (
                    asistente.generar_respuesta_automatica(consulta)
                ),
                "recomendaciones": (
                    recomendador.recomendar_respuestas_similares(consulta)
                )
            }

        if request.method == "POST":
            form = PreguntasForm(request.POST)
            if form.is_valid():
                pregunta = form.save(commit=False)
                pregunta.Usuario = usuario
                pregunta.Fecha_creacion = now
                pregunta.categoria = (
                    AsistenteIA(usuario=request.user)
                    .clasificar_pregunta(pregunta.Pregunta)
                )
                pregunta.save()
                return redirect('inicio', id=id)

        return render(request, "inicio.html", {
            "Preguntas": preguntas,
            "form": form,
            "id": id,
            "sugerencias_ia": sugerencias_ia
        })
    except Usuario.DoesNotExist:
        return redirect('index')

# Vista de respuestas
@login_required
def ViewRespuestas(request, idUser, idPregunta):
    """
    Vista para ver y responder preguntas
    """
    try:
        pregunta = Preguntas.objects.get(idPregunta=idPregunta)
        if not (
            request.user.id == pregunta.Usuario_id
            or request.user.rol in ('administrador', 'tecnico')
        ):
            return redirect('inicio', id=request.user.id)

        now = timezone.now()
        respuestas = Respuesta.objects.filter(id_Pregunta=pregunta)

        form = RespuestaForm(initial={
            'id_Pregunta': idPregunta,
            'Usuario': request.user.id,
            'FechaHora': now
        })

        if request.method == "POST":
            form = RespuestaForm(request.POST)
            if form.is_valid():
                respuesta = form.save(commit=False)
                respuesta.id_Pregunta = pregunta
                respuesta.Usuario = request.user
                respuesta.FechaHora = now
                respuesta.save()
                if request.user.rol in ('administrador', 'tecnico'):
                    pregunta.estado = 'resuelto'
                    pregunta.save(update_fields=['estado'])
                return redirect(
                    'respuestas',
                    idUser=idUser,
                    idPregunta=idPregunta
                )

        return render(request, "Respuestas.html", {
            "Pregunta": pregunta,
            "form": form,
            "Respuestas": respuestas
        })
    except Preguntas.DoesNotExist:
        return redirect('index')

# Vistas basadas en clases
class RegisterView(CreateView):
    form_class = RegisterForm
    template_name = 'register.html'
    success_url = reverse_lazy('index')

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return _redirigir_por_rol(request.user)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        request = self.request
        user = form.save()
        login(request, user)
        if user.rol == 'administrador':
            return redirect('administracion')
        return redirect('inicio', id=user.id)

class LoginView(FormView):
    form_class = LoginForm
    template_name = 'login.html'
    success_url = reverse_lazy('index')

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return _redirigir_por_rol(request.user)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        request = self.request
        usuario = form.cleaned_data.get("Usuario")
        password = form.cleaned_data.get("password")
        remember_me = form.cleaned_data['remember_me']

        user = authenticate(request, username=usuario, password=password)
        if user is not None:
            login(request, user)
            if not remember_me:
                request.session.set_expiry(0)
            if user.rol in ('administrador', 'tecnico'):
                return redirect('administracion')
            return redirect('inicio', id=user.id)
        form.add_error(None, "Usuario o contraseña incorrectos.")
        return super().form_invalid(form)
        