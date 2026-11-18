/* ============================================================================
   tema.js — Botón sol / luna y persistencia del tema de CallCenterGamer
   ----------------------------------------------------------------------------
   Responsabilidades:
   1. Alternar <html data-theme="dark|light"> al pulsar el botón de la navbar.
   2. Guardar la elección en localStorage (clave "tema"). Si el navegador la
      bloquea (modo privado, cookies restringidas) el tema sigue funcionando
      solo durante la visita, sin lanzar errores en consola.
   3. Actualizar el icono de Font Awesome, aria-pressed, title y aria-label.
   El tema inicial lo aplica el script inline del <head> (evita el parpadeo):
   sin preferencia guardada el tema por defecto es el OSCURO (identidad
   Marvel, Bloque 2A); ya no se sigue la preferencia del sistema operativo,
   que ahora solo importa si la persona elige el modo claro.
   ========================================================================== */
(function () {
    'use strict';

    var CLAVE = 'tema';
    var TEMA_POR_DEFECTO = 'dark';
    var raiz = document.documentElement;

    /* Lee la preferencia guardada. Devuelve null si no hay o si falla. */
    function leerGuardado() {
        try {
            var valor = window.localStorage.getItem(CLAVE);
            return valor === 'dark' || valor === 'light' ? valor : null;
        } catch (error) {
            return null;
        }
    }

    /* Guarda la preferencia. En modo privado puede fallar: lo ignoramos. */
    function guardar(tema) {
        try {
            window.localStorage.setItem(CLAVE, tema);
        } catch (error) {
            /* Sin almacenamiento disponible: el tema vale solo para esta visita. */
        }
    }

    function temaActual() {
        var actual = raiz.getAttribute('data-theme');
        if (actual === 'dark' || actual === 'light') {
            return actual;
        }
        return leerGuardado() || TEMA_POR_DEFECTO;
    }

    /* Sincroniza el botón con el tema activo: icono, estado y textos. */
    function pintarBoton(boton, tema) {
        var oscuro = tema === 'dark';
        var icono = boton.querySelector('i');

        if (icono) {
            icono.classList.remove(oscuro ? 'fa-moon' : 'fa-sun');
            icono.classList.add(oscuro ? 'fa-sun' : 'fa-moon');
        }

        /* aria-pressed refleja si el modo oscuro está activo. */
        boton.setAttribute('aria-pressed', oscuro ? 'true' : 'false');

        var texto = oscuro ? 'Activar modo claro' : 'Activar modo oscuro';
        boton.setAttribute('title', texto);
        boton.setAttribute('aria-label', texto);
    }

    function aplicar(tema) {
        raiz.setAttribute('data-theme', tema);

        var botones = document.querySelectorAll('[data-tema-toggle]');
        for (var i = 0; i < botones.length; i++) {
            pintarBoton(botones[i], tema);
        }
    }

    function alternar() {
        var nuevo = raiz.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        aplicar(nuevo);
        guardar(nuevo);
    }

    function iniciar() {
        var botones = document.querySelectorAll('[data-tema-toggle]');

        aplicar(temaActual());

        for (var i = 0; i < botones.length; i++) {
            botones[i].addEventListener('click', alternar);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
