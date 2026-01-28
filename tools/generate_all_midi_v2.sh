#!/bin/bash
# Generate MIDI for all BP3 grammars with ALL associated resources

BP3_DIR="/mnt/d/Claude/BP2SC/tools/bolprocessor"
CTESTS="/mnt/d/Claude/BP2SC/bp3-ctests"
OUT="$BP3_DIR/output_midi"

mkdir -p "$OUT"
cd "$BP3_DIR"

echo "=== Génération MIDI pour toutes les grammaires BP3 ==="
echo ""

count=0
success=0

# Fonction pour trouver et copier les ressources associées
copy_resources() {
    local name="$1"
    local cmd=""

    # Settings
    if [ -f "$CTESTS/-se.$name" ]; then
        cp "$CTESTS/-se.$name" "./-se.$name"
        cmd="$cmd -se ./-se.$name"
    fi

    # Alphabet (contient aussi les homomorphies)
    if [ -f "$CTESTS/-al.$name" ]; then
        cp "$CTESTS/-al.$name" "./-al.$name"
        cmd="$cmd -al ./-al.$name"
    fi

    # Sound objects
    if [ -f "$CTESTS/-so.$name" ]; then
        cp "$CTESTS/-so.$name" "./-so.$name"
    fi

    # Data file
    if [ -f "$CTESTS/-da.$name" ]; then
        cp "$CTESTS/-da.$name" "./-da.$name"
    fi

    echo "$cmd"
}

cleanup_resources() {
    local name="$1"
    rm -f "./-se.$name" "./-al.$name" "./-so.$name" "./-da.$name" "./-gr.$name" "./$name.bpgr" "./$name.bpse"
}

# Process -gr.* files
for grammar in "$CTESTS"/-gr.*; do
    [ -f "$grammar" ] || continue
    name=$(basename "$grammar" | sed 's/^-gr\.//')
    count=$((count + 1))

    printf "[%2d] %-25s " "$count" "$name"

    # Copy grammar
    cp "$grammar" "./-gr.$name"

    # Copy resources and get extra args
    extra=$(copy_resources "$name")

    # Run BP3
    if ./bp.exe produce --midiout "output_midi/${name}.mid" --seed 42 -d $extra -gr "./-gr.$name" > /tmp/bp3.log 2>&1; then
        if [ -f "output_midi/${name}.mid" ] && [ $(stat -c%s "output_midi/${name}.mid") -gt 100 ]; then
            size=$(stat -c%s "output_midi/${name}.mid")
            echo "✓ ${size}b"
            success=$((success + 1))
        else
            echo "✗ (vide)"
        fi
    else
        # Afficher l'erreur
        err=$(grep -E "Error|Cannot|failed|unknown" /tmp/bp3.log | head -1)
        echo "✗ $err"
    fi

    cleanup_resources "$name"
done

# Process .bpgr files
for grammar in "$CTESTS"/*.bpgr; do
    [ -f "$grammar" ] || continue
    base=$(basename "$grammar")
    name="${base%.bpgr}"
    count=$((count + 1))

    printf "[%2d] %-25s " "$count" "$name"

    cp "$grammar" "./$base"
    [ -f "$CTESTS/${name}.bpse" ] && cp "$CTESTS/${name}.bpse" "./${name}.bpse"

    extra=$(copy_resources "$name")

    if ./bp.exe produce --midiout "output_midi/${name}.mid" --seed 42 -d $extra -gr "./$base" > /tmp/bp3.log 2>&1; then
        if [ -f "output_midi/${name}.mid" ] && [ $(stat -c%s "output_midi/${name}.mid") -gt 100 ]; then
            size=$(stat -c%s "output_midi/${name}.mid")
            echo "✓ ${size}b"
            success=$((success + 1))
        else
            echo "✗ (vide)"
        fi
    else
        err=$(grep -E "Error|Cannot|failed|unknown" /tmp/bp3.log | head -1)
        echo "✗ $err"
    fi

    cleanup_resources "$name"
    rm -f "./$base" "./${name}.bpse"
done

echo ""
echo "=== RÉSUMÉ ==="
echo "Total: $count"
echo "Succès: $success"
echo "Échecs: $((count - success))"
