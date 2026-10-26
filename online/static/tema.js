/* ============================================================================
   tema.js — Botón sol / luna y persistencia del tema de CallCenterGamer
   ----------------------------------------------------------------------------
   Responsabilidades:
   1. Alternar <html data-theme="dark|light"> al pulsar el botón de la navbar.
   2. Guardar la elección en localStorage (clave "tema"). Si el navegador la
      bloquea (modo privado, cookies restringidas) el tema sigue funcionando
      solo durante la visita, sin lanzar errores en consola.
   3. Actualizar el icono de Font Awesome, aria-pressed, title y aria-label.
   4. Si la persona nunca eligió un tema, seguir en vivo el cambio de
      preferencia del sistema operativo.
   El tema inicial lo aplica el script inline del <head> (evita el parpadeo).
   ========================================================================== */
(function () {
    'use strict';

    var CLAVE = 'tema';
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

    /* Preferencia del sistema operativo. */
    function temaDelSistema() {
        try {
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                return 'dark';
            }
        } catch (error) {
            /* Navegador sin matchMedia: usamos el tema claro. */
        }
        return 'light';
    }

    function temaActual() {
        var actual = raiz.getAttribute('data-theme');
        if (actual === 'dark' || actual === 'light') {
            return actual;
        }
        return leerGuardado() || temaDelSistema();
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

        /* Sin elección guardada, seguimos la preferencia del sistema. */
        try {
            var consulta = window.matchMedia('(prefers-color-scheme: dark)');
            var alCambiar = function (evento) {
                if (leerGuardado() === null) {
                    aplicar(evento.matches ? 'dark' : 'light');
                }
            };
            if (consulta.addEventListener) {
                consulta.addEventListener('change', alCambiar);
            } else if (consulta.addListener) {
                consulta.addListener(alCambiar);
            }
        } catch (error) {
            /* Sin soporte de matchMedia: no hay nada que escuchar. */
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
})();
