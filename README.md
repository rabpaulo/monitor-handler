# Monitor Handler

GUI simples (GTK 4) para configurar monitores no Linux, tanto no **X11** quanto no **Wayland**.

- Resolução e taxa de atualização (Hz)
- Orientação: paisagem, retrato (90° / 270°) e invertida
- Posição: arraste os monitores no preview **ou** escolha *à direita / à esquerda / acima / abaixo* de outro monitor, com alinhamento (início, centro, fim); coordenadas X/Y manuais
- Monitor principal
- Espelhamento (duplicar tela)
- Escala (Wayland)
- VRR / FreeSync / G-Sync, HDR, profundidade de cor, faixa RGB e brilho — quando o backend suporta
- Confirmação com reversão automática em 15 s, para não ficar com a tela preta
- "Salvar para o login": gera o script/trecho de configuração para manter as alterações

## Suporte

O backend é detectado automaticamente:

| Ambiente | Ferramenta usada | Principal | Escala | Espelhar | VRR | HDR | Prof. cor | Faixa RGB | Brilho |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| X11 (dwm, i3, Openbox, XFCE…) | `xrandr` | ✔ | – | ✔ | – ¹ | – ² | ✔ (max bpc) | ✔ | ✔ (gamma) |
| GNOME (Wayland e X11) | D-Bus `org.gnome.Mutter.DisplayConfig` | ✔ | ✔ | ✔ | ✔ (GNOME 46+) | ✔ (GNOME 48+) | – | – | – |
| KDE Plasma (Wayland e X11) | `kscreen-doctor` | ✔ | ✔ | – | ✔ | ✔ | – | ✔ | – |
| Hyprland | `hyprctl` | – | ✔ | ✔ | ✔ | ✔ | ✔ | – | – |
| Sway | `swaymsg` | – | ✔ | – | ✔ | ✔ (Sway 1.11+) | ✔ | – | – |
| Outros wlroots (river, labwc, Wayfire, niri…) | `wlr-randr` | – | ✔ | – | ✔ | – | – | – | – |

¹ No X11 o VRR é ligado no driver (`Option "VariableRefresh"` no xorg.conf do amdgpu, ou `nvidia-settings`).
² O X11 não tem pipeline de HDR; use uma sessão Wayland (KDE, GNOME, Hyprland, Sway) para HDR.

Controles que o backend atual não suporta ficam escondidos.

## Instalação

Dependências: Python 3.10+, GTK 4 e PyGObject, mais a ferramenta do seu ambiente (tabela acima).

```bash
# Arch
sudo pacman -S python-gobject gtk4 xorg-xrandr      # X11
sudo pacman -S wlr-randr                            # wlroots genérico (opcional)

# Debian / Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 x11-xserver-utils

# Fedora
sudo dnf install python3-gobject gtk4 xrandr
```

Rodar direto do código:

```bash
git clone https://github.com/rabpaulo/monitor-handler.git
cd monitor-handler
./monitor-handler
```

Ou instalar (`pipx` precisa enxergar o PyGObject do sistema):

```bash
pipx install --system-site-packages .
cp data/monitor-handler.desktop ~/.local/share/applications/
```

## Uso

```bash
monitor-handler                 # abre a GUI
monitor-handler --dry-run       # GUI em modo simulação: "Aplicar" só mostra os comandos
monitor-handler --list          # lista os monitores detectados
monitor-handler --print-commands  # comando que reproduz a configuração atual
monitor-handler --backend xrandr  # força um backend
```

### Manter a configuração depois de reiniciar

- **GNOME / KDE**: salvam sozinhos.
- **X11**: clique em *Salvar para o login*; o script vai para `~/.config/monitor-handler/xrandr.sh`. Chame-o no `~/.xinitrc` (antes do `exec dwm`, por exemplo) ou no autostart do seu WM.
- **Hyprland / Sway**: *Salvar para o login* mostra as linhas `monitor = …` / `output …` para colar no arquivo de configuração.

## Desenvolvimento

```bash
python3 -m unittest discover -s tests -t .
```

Os testes de parser usam saídas reais/fixtures de cada backend; os testes da GUI precisam de um display.

## Licença

MIT
