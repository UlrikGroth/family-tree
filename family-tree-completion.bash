_family_tree_person_complete() {
    local script_dir script_path command_index command current index suggestion escaped
    local -a helper_command
    COMPREPLY=()

    [[ ${COMP_WORDS[0]##*/} == python* ]] || return 0
    script_path=${COMP_WORDS[1]}
    script_path=${script_path#\"}
    script_path=${script_path%\"}
    script_path=${script_path#\'}
    script_path=${script_path%\'}
    [[ ${script_path##*/} == main.py ]] || return 0

    command_index=-1
    command=
    for ((index = 2; index < COMP_CWORD; index++)); do
        if [[ ${COMP_WORDS[index]} == --database ]]; then
            ((index++))
            continue
        fi
        case ${COMP_WORDS[index]} in
            add|a|new|n|list|ls|export-dot|dot|complete-people|show|s|distance|rel|edit|e|\
            parent|p|edit-parent|ep|unlink-parent|up|partner|pair|unlink-partner|unpair|\
            edit-partner|epair|clear-parents|cp|clear-children|cc|clear-partners|cpartners|\
            review-parents|review|tree|t)
                command_index=$index
                command=${COMP_WORDS[index]}
                break
                ;;
        esac
    done
    (( command_index >= 0 )) || return 0

    case $command in
        s) command=show ;;
        e) command=edit ;;
        rel) command=distance ;;
        p) command=parent ;;
        ep) command=edit-parent ;;
        up) command=unlink-parent ;;
        pair) command=partner ;;
        unpair) command=unlink-partner ;;
        epair) command=edit-partner ;;
        t) command=tree ;;
        cp) command=clear-parents ;;
        cc) command=clear-children ;;
        cpartners) command=clear-partners ;;
    esac

    case $command in
        show|edit|clear-parents|clear-children|clear-partners)
            (( COMP_CWORD == command_index + 1 )) || return 0
            ;;
        distance|edit-parent|unlink-parent|partner|unlink-partner|edit-partner)
            (( COMP_CWORD == command_index + 1 || COMP_CWORD == command_index + 2 )) || return 0
            ;;
        tree)
            (( COMP_CWORD == command_index + 1 )) || return 0
            [[ " ${COMP_WORDS[*]} " != *" --all "* ]] || return 0
            ;;
        parent)
            for ((index = command_index + 1; index < COMP_CWORD; index++)); do
                [[ ${COMP_WORDS[index]} == --* ]] && return 0
            done
            ;;
        *)
            return 0
            ;;
    esac

    current=${COMP_WORDS[COMP_CWORD]}
    [[ $current == -* ]] && return 0
    script_dir=$(cd -- "$(dirname -- "$script_path")" && pwd) || return 0
    helper_command=(python3 "$script_dir/main.py")
    if [[ -n ${FAMILY_TREE_DATABASE:-} ]]; then
        helper_command+=(--database "$FAMILY_TREE_DATABASE")
    fi
    helper_command+=(complete-people "$current")
    while IFS= read -r suggestion; do
        printf -v escaped '%q' "$suggestion"
        COMPREPLY+=("$escaped")
    done < <("${helper_command[@]}" 2>/dev/null)
}

complete -o default -F _family_tree_person_complete python python3
if [[ $- == *i* ]]; then
    bind '"\C-i": menu-complete'
fi
