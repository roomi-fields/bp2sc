#!/bin/bash
# Generate MIDI for all BP3 grammars with proper note conventions

BP3_DIR="/mnt/d/Claude/BP2SC/tools/bolprocessor"
CTESTS="/mnt/d/Claude/BP2SC/bp3-ctests"
OUT="$BP3_DIR/output_midi"

mkdir -p "$OUT"
cd "$BP3_DIR"

echo "=== Génération MIDI pour 55 grammaires BP3 ==="
echo ""

count=0
success=0

# Détecter la convention de notes depuis le fichier settings ou le contenu
detect_convention() {
    local name="$1"
    local se_file="$CTESTS/-se.$name"
    local gr_file="$2"

    # Vérifier le settings file
    if [ -f "$se_file" ]; then
        conv=$(grep -o '"NoteConvention"[^}]*"value"[^"]*"[0-9]"' "$se_file" | grep -o '"[0-9]"' | tr -d '"')
        case "$conv" in
            0) echo "--english"; return ;;
            1) echo "--french"; return ;;
            2) echo "--indian"; return ;;
        esac
    fi

    # Détecter depuis le contenu de la grammaire
    if grep -qE '\b(do[0-9]|re[0-9]|mi[0-9]|fa[0-9]|sol[0-9]|la[0-9]|si[0-9])\b' "$gr_file" 2>/dev/null; then
        echo "--french"
    elif grep -qE '\b(sa[0-9]|ri[0-9]|ga[0-9]|ma[0-9]|pa[0-9]|dha[0-9]|ni[0-9])\b' "$gr_file" 2>/dev/null; then
        echo "--indian"
    else
        echo "--english"
    fi
}

process_grammar() {
    local name="$1"
    local gr_file="$2"
    local base=$(basename "$gr_file")

    # Copy grammar
    cp "$gr_file" "./$base"

    # Build command
    local cmd="./bp.exe produce --midiout output_midi/${name}.mid --seed 42 -d"

    # Detect and add note convention
    local conv=$(detect_convention "$name" "$gr_file")
    cmd="$cmd $conv"

    # Add resources if they exist
    [ -f "$CTESTS/-se.$name" ] && cp "$CTESTS/-se.$name" "./-se.$name" && cmd="$cmd -se ./-se.$name"
    [ -f "$CTESTS/-al.$name" ] && cp "$CTESTS/-al.$name" "./-al.$name" && cmd="$cmd -al ./-al.$name"
    [ -f "$CTESTS/-so.$name" ] && cp "$CTESTS/-so.$name" "./-so.$name"

    # Add grammar
    cmd="$cmd -gr ./$base"

    # Run BP3
    if $cmd > /tmp/bp3.log 2>&1; then
        if [ -f "output_midi/${name}.mid" ] && [ $(stat -c%s "output_midi/${name}.mid" 2>/dev/null || echo 0) -gt 100 ]; then
            size=$(stat -c%s "output_midi/${name}.mid")
            echo "✓ ${size}b ($conv)"
            success=$((success + 1))
        else
            echo "✗ vide"
        fi
    else
        err=$(grep -E "Error|Cannot|failed" /tmp/bp3.log 2>/dev/null | head -1 | cut -c1-50)
        echo "✗ $err"
    fi

    # Cleanup
    rm -f "./$base" "./-se.$name" "./-al.$name" "./-so.$name"
}

# Process -gr.* files
for grammar in "$CTESTS"/-gr.*; do
    [ -f "$grammar" ] || continue
    name=$(basename "$grammar" | sed 's/^-gr\.//')
    count=$((count + 1))
    printf "[%2d] %-25s " "$count" "$name"
    process_grammar "$name" "$grammar"
done

# Process .bpgr files
for grammar in "$CTESTS"/*.bpgr; do
    [ -f "$grammar" ] || continue
    name=$(basename "$grammar" .bpgr)
    count=$((count + 1))
    printf "[%2d] %-25s " "$count" "$name"
    process_grammar "$name" "$grammar"
done

echo ""
echo "=== RÉSUMÉ ==="
echo "Total: $count"
echo "Succès: $success ($((success * 100 / count))%)"
echo "Échecs: $((count - success))"
