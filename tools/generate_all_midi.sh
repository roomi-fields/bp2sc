#!/bin/bash
# Generate MIDI files for all 55 BP3 grammars using BP3 executable

set -e

BP3_DIR="/mnt/d/Claude/BP2SC/tools/bolprocessor"
CTESTS_DIR="/mnt/d/Claude/BP2SC/bp3-ctests"
OUTPUT_DIR="$BP3_DIR/output_midi"

mkdir -p "$OUTPUT_DIR"
cd "$BP3_DIR"

echo "=== Generating MIDI for all BP3 grammars ==="
echo "Output: $OUTPUT_DIR"
echo ""

count=0
success=0
failed=0

# Process -gr.* files
for grammar in "$CTESTS_DIR"/-gr.*; do
    if [ -f "$grammar" ]; then
        name=$(basename "$grammar" | sed 's/^-gr\.//')
        count=$((count + 1))

        echo -n "[$count] $name... "

        # Copy grammar file locally
        cp "$grammar" "./-gr.$name"

        # Copy associated files if they exist
        [ -f "$CTESTS_DIR/-se.$name" ] && cp "$CTESTS_DIR/-se.$name" "./-se.$name"
        [ -f "$CTESTS_DIR/-al.$name" ] && cp "$CTESTS_DIR/-al.$name" "./-al.$name"
        [ -f "$CTESTS_DIR/-ho.$name" ] && cp "$CTESTS_DIR/-ho.$name" "./-ho.$name"

        # Build command with settings if available
        cmd="./bp.exe produce --midiout output_midi/${name}.mid --seed 42 -d"
        [ -f "./-se.$name" ] && cmd="$cmd -se ./-se.$name"
        [ -f "./-al.$name" ] && cmd="$cmd -al ./-al.$name"
        cmd="$cmd -gr ./-gr.$name"

        # Run BP3
        if $cmd > /tmp/bp3_out.txt 2>&1; then
            if [ -f "output_midi/${name}.mid" ]; then
                size=$(stat -c%s "output_midi/${name}.mid" 2>/dev/null || echo "0")
                if [ "$size" -gt 100 ]; then
                    echo "✓ (${size}b)"
                    success=$((success + 1))
                else
                    echo "✗ (empty)"
                    failed=$((failed + 1))
                fi
            else
                echo "✗ (no MIDI)"
                failed=$((failed + 1))
            fi
        else
            echo "✗ (error)"
            failed=$((failed + 1))
        fi

        # Cleanup local copies
        rm -f "./-gr.$name" "./-se.$name" "./-al.$name" "./-ho.$name"
    fi
done

# Process .bpgr files
for grammar in "$CTESTS_DIR"/*.bpgr; do
    if [ -f "$grammar" ]; then
        base=$(basename "$grammar")
        name="${base%.bpgr}"
        count=$((count + 1))

        echo -n "[$count] $name... "

        # Copy grammar file
        cp "$grammar" "./$base"

        # Copy associated settings
        [ -f "$CTESTS_DIR/${name}.bpse" ] && cp "$CTESTS_DIR/${name}.bpse" "./${name}.bpse"
        [ -f "$CTESTS_DIR/-se.:${name}.bpse" ] && cp "$CTESTS_DIR/-se.:${name}.bpse" "./-se.:${name}.bpse"

        # Build command
        cmd="./bp.exe produce --midiout output_midi/${name}.mid --seed 42 -d -gr ./$base"

        # Run BP3
        if $cmd > /tmp/bp3_out.txt 2>&1; then
            if [ -f "output_midi/${name}.mid" ]; then
                size=$(stat -c%s "output_midi/${name}.mid" 2>/dev/null || echo "0")
                if [ "$size" -gt 100 ]; then
                    echo "✓ (${size}b)"
                    success=$((success + 1))
                else
                    echo "✗ (empty)"
                    failed=$((failed + 1))
                fi
            else
                echo "✗ (no MIDI)"
                failed=$((failed + 1))
            fi
        else
            echo "✗ (error)"
            failed=$((failed + 1))
        fi

        # Cleanup
        rm -f "./$base" "./${name}.bpse" "./-se.:${name}.bpse"
    fi
done

echo ""
echo "=== Summary ==="
echo "Total: $count"
echo "Success: $success"
echo "Failed: $failed"

# Copy results to comparison directory
echo ""
echo "Copying results..."
mkdir -p /mnt/d/Claude/BP2SC/comparison_output/bp3_midi
cp output_midi/*.mid /mnt/d/Claude/BP2SC/comparison_output/bp3_midi/ 2>/dev/null || true
echo "Done! MIDI files in: /mnt/d/Claude/BP2SC/comparison_output/bp3_midi/"
