#!/system/bin/sh
# Reconstructed fixed M2.8D probe. Raw logcat/process output is consumed only
# on-device; stdout contains a strict, filtered P3A28D protocol.
set -f
LC_ALL=C
export LC_ALL

emit_error() {
    printf 'P3A28D\tBEGIN\t1\nP3A28D\tFILTER\tpid-marker-numeric-v1\nP3A28D\tEND\tERROR\t%s\n' "$1"
    exit 1
}

process_table=$(ps -A -o PID,NAME 2>/dev/null)
ps_status=$?
if [ "$ps_status" -ne 0 ]; then
    emit_error REMOTE_FILTER_UNVERIFIED
fi

process_rows=$(printf '%s\n' "$process_table" | awk '
BEGIN { FS = "[ \t]+" }
NR == 1 {
    if (NF != 2 || $1 != "PID" || $2 != "NAME") bad = 1
    else header = 1
    next
}
{
    if (NF != 2 || $1 !~ /^[0-9]+$/ || length($1) > 10) {
        bad = 1
        next
    }
    name = $2
    lower = tolower(name)
    if (lower ~ /(quickcamera|pvr|camera.*hidl|hidl.*camera)/) {
        if (length(name) < 1 || length(name) > 256 || name !~ /^[A-Za-z0-9_.:@-]+$/) {
            bad = 1
            next
        }
        count++
        if (count > 16) {
            too_many = 1
            next
        }
        printf "%s\t%s\n", $1, name
    }
}
END {
    if (!header) exit 2
    if (bad) exit 3
    if (too_many) exit 4
}' 2>/dev/null)
process_status=$?
case "$process_status" in
    0) ;;
    4) emit_error OUTPUT_LINE_LIMIT ;;
    *) emit_error REMOTE_FILTER_UNVERIFIED ;;
esac

if [ -n "$process_rows" ]; then
    process_count=$(printf '%s\n' "$process_rows" | awk 'END { print NR }' 2>/dev/null)
else
    process_count=0
fi

if [ "$process_count" -eq 0 ]; then
    printf 'P3A28D\tBEGIN\t1\nP3A28D\tFILTER\tpid-marker-numeric-v1\nP3A28D\tEND\tNO_TARGET_PROCESSES\n'
    exit 0
fi

# Command substitution captures logcat stdout locally so its real exit status
# is available without a pipeline sentinel. stderr never leaves the device.
logcat_output=$(logcat -b main -d -v threadtime -t 256 2>/dev/null)
logcat_status=$?
if [ "$logcat_status" -ne 0 ]; then
    emit_error REMOTE_COMMAND_FAILURE
fi
if [ "${#logcat_output}" -gt 262144 ]; then
    emit_error OUTPUT_TRUNCATED
fi

normalized=$(printf '%s\n' "$logcat_output" | awk -v process_rows="$process_rows" -v process_count="$process_count" '
function set_error(code) {
    if (error_code == "") error_code = code
}
function valid_i64(value, digits, negative, limit, i, a, b) {
    if (value !~ /^-?(0|[1-9][0-9]*)$/ || length(value) > 20) return 0
    negative = (substr(value, 1, 1) == "-")
    digits = negative ? substr(value, 2) : value
    sub(/^0+/, "", digits)
    if (digits == "") digits = "0"
    if (length(digits) > 19) return 0
    if (length(digits) < 19) return 1
    limit = negative ? "9223372036854775808" : "9223372036854775807"
    for (i = 1; i <= 19; i++) {
        a = index("0123456789", substr(digits, i, 1)) - 1
        b = index("0123456789", substr(limit, i, 1)) - 1
        if (a < b) return 1
        if (a > b) return 0
    }
    return 1
}
function value_for(text, key, p, tail, stop) {
    p = index(text, key "=")
    if (p == 0) return ""
    tail = substr(text, p + length(key) + 1)
    stop = match(tail, /[, \t]/)
    if (stop > 0) tail = substr(tail, 1, stop - 1)
    return tail
}
function error_envelope(code) {
    print "P3A28D\tBEGIN\t1"
    print "P3A28D\tFILTER\tpid-marker-numeric-v1"
    print "P3A28D\tEND\tERROR\t" code
}
BEGIN {
    if (process_count < 1 || process_count > 16) set_error("REMOTE_FILTER_UNVERIFIED")
    pair_count = split(process_rows, pairs, "\n")
    if (pair_count != process_count) set_error("REMOTE_FILTER_UNVERIFIED")
    for (i = 1; i <= pair_count; i++) {
        field_count = split(pairs[i], fields, "\t")
        if (field_count != 2 || fields[1] !~ /^[0-9]+$/ || fields[2] !~ /^[A-Za-z0-9_.:@-]+$/) {
            set_error("REMOTE_FILTER_UNVERIFIED")
        } else {
            process_name[fields[1]] = fields[2]
        }
    }
    marker = "CSLTimestampTypeQtimer frameMessage:"
}
{
    line = $0
    sub(/\r$/, "", line)
    if (length(line) > 4096) {
        set_error("OUTPUT_TRUNCATED")
        next
    }
    if (index(line, marker) == 0) next
    if (line ~ /[[:cntrl:]]/) {
        set_error("MALFORMED_PROTOCOL_RECORD")
        next
    }
    split(line, columns, /[ \t]+/)
    pid = columns[3]
    if (pid !~ /^[0-9]+$/ || length(pid) > 10) {
        set_error("MALFORMED_PROTOCOL_RECORD")
        next
    }
    if (!(pid in process_name)) next
    if (columns[1] !~ /^[0-9][0-9]-[0-9][0-9]$/ || columns[2] !~ /^[0-9][0-9]:[0-9][0-9]:[0-9][0-9][.][0-9][0-9][0-9]$/) {
        set_error("MALFORMED_PROTOCOL_RECORD")
        next
    }
    message = substr(line, index(line, marker) + length(marker))
    request_id = value_for(message, "requestID")
    frame_count = value_for(message, "frameCount")
    timestamp = value_for(message, "timestamp")
    mono_timestamp = value_for(message, "monoTimestamp")
    if (!valid_i64(request_id) || !valid_i64(frame_count) || !valid_i64(timestamp) || !valid_i64(mono_timestamp)) {
        set_error("MALFORMED_PROTOCOL_RECORD")
        next
    }
    event_count++
    events[event_count] = "P3A28D\tEVENT\t" pid "\t" columns[1] "\t" columns[2] "\t" request_id "\t" frame_count "\t" timestamp "\t" mono_timestamp "\tCSLTimestampTypeQtimer"
}
END {
    if (error_code != "") {
        error_envelope(error_code)
        exit 1
    }
    total = 3 + process_count + event_count
    if (total > 40) {
        error_envelope("OUTPUT_LINE_LIMIT")
        exit 1
    }
    output[1] = "P3A28D\tBEGIN\t1"
    output[2] = "P3A28D\tFILTER\tpid-marker-numeric-v1"
    row = 2
    for (i = 1; i <= pair_count; i++) {
        split(pairs[i], fields, "\t")
        output[++row] = "P3A28D\tPROCESS\t" fields[1] "\t" fields[2]
    }
    for (i = 1; i <= event_count; i++) output[++row] = events[i]
    output[++row] = "P3A28D\tEND\tOK"
    bytes = 0
    for (i = 1; i <= row; i++) bytes += length(output[i]) + 1
    if (bytes > 65536) {
        error_envelope("OUTPUT_TRUNCATED")
        exit 1
    }
    for (i = 1; i <= row; i++) print output[i]
}' 2>/dev/null)
awk_status=$?
if [ "$awk_status" -ne 0 ]; then
    # Preserve only known error envelopes. Never trust arbitrary AWK stdout
    # when an Android Toybox/awk implementation fails or differs.
    for error_code in OUTPUT_LINE_LIMIT OUTPUT_TRUNCATED MALFORMED_PROTOCOL_RECORD; do
        expected=$(printf 'P3A28D\tBEGIN\t1\nP3A28D\tFILTER\tpid-marker-numeric-v1\nP3A28D\tEND\tERROR\t%s' "$error_code")
        if [ "$normalized" = "$expected" ]; then
            emit_error "$error_code"
        fi
    done
    emit_error REMOTE_FILTER_UNVERIFIED
fi

# Validate the entire generated protocol with shell builtins before allowing
# any AWK-produced bytes to cross the ADB boundary. This rejects incompatible
# helpers that print their input or arbitrary diagnostics even with status 0.
TAB=$(printf '\t')
NL='
'
validation_failed=0
line_count=0
process_records=0
event_records=0
events_started=0
end_seen=0
last_line=
valid_signed_decimal() {
    value=$1
    case "$value" in -*) digits=${value#-} ;; *) digits=$value ;; esac
    case "$digits" in ''|*[!0-9]*) return 1 ;; esac
    [ "${#value}" -le 20 ]
}
while IFS= read -r protocol_line || [ -n "$protocol_line" ]; do
    line_count=$((line_count + 1))
    last_line=$protocol_line
    if [ "$line_count" -gt 40 ] || [ "${#protocol_line}" -gt 1024 ] || [ "$end_seen" -ne 0 ]; then
        validation_failed=1
        break
    fi
    case "$line_count" in
        1)
            [ "$protocol_line" = "P3A28D${TAB}BEGIN${TAB}1" ] || validation_failed=1
            continue
            ;;
        2)
            [ "$protocol_line" = "P3A28D${TAB}FILTER${TAB}pid-marker-numeric-v1" ] || validation_failed=1
            continue
            ;;
    esac
    case "$protocol_line" in
        "P3A28D${TAB}PROCESS${TAB}"*)
            if [ "$events_started" -ne 0 ]; then validation_failed=1; break; fi
            payload=${protocol_line#"P3A28D${TAB}PROCESS${TAB}"}
            case "$payload" in *"$TAB"*) ;; *) validation_failed=1; break ;; esac
            IFS="$TAB" read -r record_pid record_name record_extra <<EOF_PROCESS
$payload
EOF_PROCESS
            case "$record_pid" in ''|*[!0-9]*) validation_failed=1 ;; esac
            case "$record_name" in ''|*[!A-Za-z0-9_.:@-]*) validation_failed=1 ;; esac
            case "$record_extra" in '') ;; *) validation_failed=1 ;; esac
            if [ "${#record_pid}" -gt 10 ] || [ "${#record_name}" -gt 256 ]; then validation_failed=1; fi
            process_records=$((process_records + 1))
            if [ "$process_records" -gt 16 ]; then validation_failed=1; fi
            ;;
        "P3A28D${TAB}EVENT${TAB}"*)
            events_started=1
            payload=${protocol_line#"P3A28D${TAB}EVENT${TAB}"}
            IFS="$TAB" read -r record_pid record_date record_time record_request record_frame record_timestamp record_mono record_source record_extra <<EOF_EVENT
$payload
EOF_EVENT
            case "$record_pid" in ''|*[!0-9]*) validation_failed=1 ;; esac
            case "$record_date" in [0-9][0-9]-[0-9][0-9]) ;; *) validation_failed=1 ;; esac
            case "$record_time" in [0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9]) ;; *) validation_failed=1 ;; esac
            valid_signed_decimal "$record_request" || validation_failed=1
            valid_signed_decimal "$record_frame" || validation_failed=1
            valid_signed_decimal "$record_timestamp" || validation_failed=1
            valid_signed_decimal "$record_mono" || validation_failed=1
            [ "$record_source" = CSLTimestampTypeQtimer ] || validation_failed=1
            [ -z "$record_extra" ] || validation_failed=1
            [ "${#record_pid}" -le 10 ] || validation_failed=1
            case "$process_rows" in
                "$record_pid$TAB"*|*"$NL$record_pid$TAB"*) ;;
                *) validation_failed=1 ;;
            esac
            event_records=$((event_records + 1))
            ;;
        "P3A28D${TAB}END${TAB}OK")
            end_seen=1
            ;;
        *)
            validation_failed=1
            ;;
    esac
    if [ "$validation_failed" -ne 0 ]; then break; fi
done <<EOF_PROTOCOL
$normalized
EOF_PROTOCOL

if [ "$validation_failed" -ne 0 ] || [ "$line_count" -lt 3 ] || \
   [ "$last_line" != "P3A28D${TAB}END${TAB}OK" ] || [ "$end_seen" -ne 1 ] || \
   [ "$process_records" -ne "$process_count" ] || \
   [ "$((3 + process_records + event_records))" -ne "$line_count" ] || \
   [ "${#normalized}" -gt 65535 ]; then
    emit_error REMOTE_FILTER_UNVERIFIED
fi

printf '%s\n' "$normalized"
exit 0
