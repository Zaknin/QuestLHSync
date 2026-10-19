#!/system/bin/sh
# RECONSTRUCTED M2.8C probe. This is not the unrecovered original probe.
# Its only stdout is the versioned P3A28C protocol; raw logcat lines stay in awk.

set -f
LC_ALL=C
export LC_ALL

emit_error() {
    printf 'P3A28C\tBEGIN\t1\nP3A28C\tFILTER\tpid-marker-numeric-v1\nP3A28C\tEND\tERROR\t%s\n' "$1"
    exit 1
}

process_table=$(ps -A -o PID,NAME 2>/dev/null)
ps_status=$?
if [ "$ps_status" -ne 0 ]; then
    emit_error REMOTE_COMMAND_FAILURE
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
    printf 'P3A28C\tBEGIN\t1\nP3A28C\tFILTER\tpid-marker-numeric-v1\nP3A28C\tEND\tNOT_OBSERVED\tNO_TARGET_PROCESSES\n'
    exit 0
fi

status_token="__P3A28C_STATUS_$$__"
{
    logcat -b main -d -v threadtime -t 256
    logcat_status=$?
    printf '\n%s\t%d\n' "$status_token" "$logcat_status"
} | awk -v token="$status_token" -v process_rows="$process_rows" -v process_count="$process_count" '
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
function valid_u32(value, digits, limit, i, a, b) {
    if (value !~ /^(0|[1-9][0-9]*)$/ || length(value) > 10) return 0
    digits = value
    sub(/^0+/, "", digits)
    if (digits == "") digits = "0"
    if (length(digits) < 10) return 1
    if (length(digits) > 10) return 0
    limit = "4294967295"
    for (i = 1; i <= 10; i++) {
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
    print "P3A28C\tBEGIN\t1"
    print "P3A28C\tFILTER\tpid-marker-numeric-v1"
    print "P3A28C\tEND\tERROR\t" code
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
    status_prefix = token "\t"
}
{
    line = $0
    sub(/\r$/, "", line)
    if (index(line, status_prefix) == 1) {
        tail = substr(line, length(status_prefix) + 1)
        if (tail !~ /^[0-9]+$/ || status_seen) set_error("MALFORMED_PROTOCOL_RECORD")
        else {
            status_seen++
            logcat_status = tail + 0
        }
        next
    }
    if (status_seen) {
        if (length(line) > 0) set_error("MALFORMED_PROTOCOL_RECORD")
        next
    }
    if (length(line) > 4096) {
        set_error("OUTPUT_TRUNCATED")
        next
    }
    if (index(line, marker) == 0) {
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
    if (!valid_i64(request_id) || !valid_u32(frame_count) || !valid_i64(timestamp) || !valid_i64(mono_timestamp)) {
        set_error("MALFORMED_PROTOCOL_RECORD")
        next
    }
    event_count++
    events[event_count] = "P3A28C\tEVENT\t" pid "\t" columns[1] "\t" columns[2] "\t" request_id "\t" frame_count "\t" timestamp "\t" mono_timestamp "\tCSLTimestampTypeQtimer"
}
END {
    if (status_seen != 1) set_error("MISSING_PROTOCOL_TERMINATOR")
    if (logcat_status != 0) {
        set_error("REMOTE_COMMAND_FAILURE")
    }
    if (error_code != "") {
        error_envelope(error_code)
        exit 1
    }
    total = 3 + process_count + event_count
    if (total > 40) {
        error_envelope("OUTPUT_LINE_LIMIT")
        exit 1
    }
    output[1] = "P3A28C\tBEGIN\t1"
    output[2] = "P3A28C\tFILTER\tpid-marker-numeric-v1"
    row = 2
    for (i = 1; i <= pair_count; i++) {
        split(pairs[i], fields, "\t")
        output[++row] = "P3A28C\tPROCESS\t" fields[1] "\t" fields[2]
    }
    for (i = 1; i <= event_count; i++) output[++row] = events[i]
    output[++row] = "P3A28C\tEND\tOK"
    bytes = 0
    for (i = 1; i <= row; i++) bytes += length(output[i]) + 1
    if (bytes > 65536) {
        error_envelope("OUTPUT_TRUNCATED")
        exit 1
    }
    for (i = 1; i <= row; i++) print output[i]
}'
