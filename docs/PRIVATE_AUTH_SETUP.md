# Configuración del acceso privado de Sports Predictor

Esta aplicación está configurada para un único administrador. No existe registro público ni se aceptan cuentas adicionales aunque alguien conozca la dirección del sitio.

## 1. Crear la cuenta propietaria en Supabase

1. Abre el proyecto Supabase que ya utiliza Sports Predictor.
2. En Authentication / Users, crea manualmente una cuenta con el correo que será el único administrador.
3. Confirma/verifica ese correo y establece una contraseña larga y exclusiva (recomendado: 16 caracteres o más).
4. En Authentication / Settings, desactiva los registros públicos (Allow new users to sign up) y activa la protección contra contraseñas filtradas si está disponible.
5. Mantén habilitada la autenticación TOTP. Sports Predictor exige completar el segundo factor antes de permitir cualquier endpoint privado.
6. En los ajustes de Auth, conserva límites de intentos de inicio de sesión estrictos y activa los controles de protección contra abuso disponibles.
7. Configura el tiempo máximo de sesión y el tiempo de inactividad de acuerdo con el uso privado; se recomienda una sesión inactiva máxima de 12 horas.
8. Reduce la duración del access token JWT a 15–30 minutos y confirma que la rotación de refresh tokens esté habilitada; esto reduce la ventana de exposición de un token copiado después de cerrar sesión.

No compartas ni guardes la contraseña en GitHub, Render logs o código fuente.

## 2. Variables privadas en Render

En el servicio de Sports Predictor, agrega o confirma estas variables:

| Variable | Valor |
|---|---|
| SUPABASE_URL | URL HTTPS del proyecto Supabase (ya utilizada por la aplicación) |
| SUPABASE_SERVICE_ROLE_KEY | Clave de servidor existente; nunca exponer al navegador |
| SUPABASE_ANON_KEY | Clave anon/publicable del mismo proyecto Supabase |
| SPORTS_PREDICTOR_ADMIN_EMAIL | El correo exacto de la cuenta propietaria |
| AUTH_COOKIE_SECURE | true |

No introduzcas claves reales en archivos del repositorio. Render debe mantenerlas como variables de entorno privadas. La clave anon/publicable no sustituye ni debe confundirse con la service-role key.

## 3. Primer acceso y TOTP

1. Abre la aplicación por su URL HTTPS de Render.
2. Inicia sesión con el correo y contraseña creados en Supabase.
3. En el primer acceso, selecciona Activar segundo factor.
4. Añade la clave mostrada a una aplicación autenticadora compatible con TOTP.
5. Introduce el código actual de seis dígitos para completar el enrolamiento.
6. Guarda de forma segura el acceso a la aplicación autenticadora. Si pierdes el dispositivo, recupera el acceso desde el panel de Supabase tras verificar tu identidad; no existe un bypass de MFA dentro de Sports Predictor.

La clave TOTP se muestra durante el enrolamiento y no se persiste en la aplicación. Si se cierra la sesión antes de terminar el enrolamiento y no se guardó la clave, elimina el factor TOTP no verificado desde el panel de Supabase y vuelve a iniciar la configuración.

## 4. Controles implementados

- La API, Swagger, ReDoc y OpenAPI requieren una sesión válida y MFA completado.
- Cuenta permitida por lista blanca de correo configurada en el servidor.
- Validación de contraseña y gestión de sesiones mediante Supabase Auth.
- Cookies de sesión HttpOnly, Secure y SameSite=Strict; el navegador no puede leer los tokens.
- Renovación de sesión con refresh token rotatorio y cierre de sesión con revocación en Supabase.
- Verificación de origen para operaciones que modifican datos.
- Cabeceras de seguridad: HSTS bajo HTTPS, protección contra MIME sniffing, framing y políticas de permisos.
- La aplicación falla cerrada: sin configuración de autenticación o sin verificación de sesión, la API privada no responde con datos.
- Validación remota de sesión con una caché breve de 20 segundos para reducir llamadas repetidas a Supabase.

## 5. Antes de habilitar el acceso

Configura las variables en Render antes de integrar/desplegar esta funcionalidad. Después del despliegue, comprueba el inicio de sesión, el enrolamiento TOTP, el acceso normal, la renovación de sesión y el cierre de sesión. No compartas capturas que muestren claves TOTP, cookies o tokens.
