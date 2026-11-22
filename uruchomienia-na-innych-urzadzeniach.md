# Dostęp do dashboardu z innych urządzeń

Tak, da się, i aplikacja jest do tego przygotowana. Robi się to przez **Tailscale**, a nie przez
bezpośrednie wystawienie portu.

## Jak to działa

Dashboard słucha **tylko na `127.0.0.1:8765`**. To celowe: `Settings.from_env`
(`appcheck/web/settings.py`) odmawia startu, jeśli `DASHBOARD_HOST` nie jest adresem lokalnym.
Inne urządzenia łączą się przez prywatną sieć Tailscale. Na komputerze z aplikacją `tailscale serve`
przyjmuje ruch HTTPS z Twojego tailnetu i przekazuje go na lokalny port.

```
telefon/laptop ──(Tailscale, HTTPS)──► Windows: tailscale serve ──► localhost:8765 ──► WSL: dashboard
```

## Kroki

1. Zainstaluj Tailscale na **Windows** (nie w WSL) i na każdym urządzeniu, z którego chcesz korzystać.
   Zaloguj się wszędzie tym samym kontem.
2. W panelu Tailscale (Admin console → DNS) włącz **MagicDNS** i **HTTPS Certificates**.
3. Na Windows, w PowerShell:

   ```
   tailscale serve --bg 8765
   ```

   Polecenie wypisze adres `https://<komputer>.<tailnet>.ts.net`.
4. Wpisz tę nazwę hosta do `.env`:

   ```
   DASHBOARD_ALLOWED_HOSTS=<komputer>.<tailnet>.ts.net
   ```

   Potem uruchom dashboard ponownie: `scripts/start-dashboard.sh`.
5. Na drugim urządzeniu otwórz ten adres i zaloguj się tokenem z `DASHBOARD_TOKEN`. Na telefonie
   możesz potem wybrać „Zainstaluj aplikację” (PWA).

Bez kroku 4 dashboard odrzuci żądania, bo zna tylko dozwolone nazwy hosta (to ochrona przed DNS
rebinding). WSL2 przekazuje `localhost` do Windows, więc `tailscale serve` po stronie Windows widzi
port z WSL.

## Czego nie robić

- **Bezpośrednio w sieci lokalnej (`http://192.168.x.x:8765`)** to nie zadziała, i to z dwóch
  powodów. Kod blokuje adres inny niż lokalny, a ciasteczko sesji `__Host-session` ma flagę `Secure`,
  więc bez HTTPS przeglądarka go nie zapisze. Obejście wymagałoby zmian w kodzie i osłabiłoby
  zabezpieczenia.
- **`tailscale funnel` ani przekierowanie portu na routerze.** To wystawiłoby dashboard do
  publicznego internetu. A dashboard ma dostęp do haseł z `.env`, do tokenu GitHuba i do przycisku
  Kill sesji Claude Code.

## Dostęp dla kogoś innego

Jeśli z dashboardu ma korzystać inna osoba z własnym kontem Tailscale, możesz jej udostępnić tylko ten
komputer (w Admin console: Machines → Share). Nie trzeba dodawać jej do całego tailnetu. Musi też
dostać token. Pamiętaj, że token daje pełny dostęp do dashboardu, łącznie z przyciskiem Kill.

## Utrata urządzenia

Zmień `DASHBOARD_TOKEN` i zrestartuj dashboard, co wylogowuje wszystkie sesje. Potem usuń urządzenie
z tailnetu w panelu Tailscale.
