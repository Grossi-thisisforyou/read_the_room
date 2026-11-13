# Infinite Jest shell look for SSH and console logins.
# Installed to /etc/profile.d/ by install.sh. Only touches interactive bash.
case "$-" in *i*) ;; *) return ;; esac
[ -n "$BASH_VERSION" ] || return

# bone on near-black, flesh and rust accents
_ij_bone='\[\e[38;2;226;214;196m\]'
_ij_flesh='\[\e[38;2;196;98;92m\]'
_ij_rust='\[\e[38;2;170;60;28m\]'
_ij_dim='\[\e[38;2;110;96;98m\]'
_ij_off='\[\e[0m\]'

# prompt: ♛ inartwetrust ~/path ©
PS1="${_ij_rust}\342\231\233 ${_ij_flesh}\h ${_ij_bone}\w ${_ij_dim}\$(date +%H:%M)${_ij_rust} \302\251 ${_ij_off}"
unset _ij_bone _ij_flesh _ij_rust _ij_dim _ij_off

alias temp='vcgencmd measure_temp; vcgencmd get_throttled'
alias heat='watch -n 2 "vcgencmd measure_temp; vcgencmd get_throttled"'
