set -f
PROC_ROOT='/proc'
MAX_PROCESSES=40
MAX_RECORDS=40
record_count=0
scan_status=COMPLETE
stop_scan=0
NL=$(printf '\n_'); NL=${NL%_}

reserve_record() {
  if [ "$record_count" -ge "$MAX_RECORDS" ]; then
    scan_status=LIMIT_REACHED
    stop_scan=1
    return 1
  fi
  record_count=$((record_count + 1))
  return 0
}

read_starttime() {
  pid_value=$1
  stat_line=$(cat "$PROC_ROOT/$pid_value/stat" 2>/dev/null) || return 1
  stat_tail=$(printf '%s\n' "$stat_line" | sed 's/^.*) //') || return 1
  printf '%s\n' "$stat_tail" | awk 'NF >= 20 && $20 ~ /^[0-9]+$/ { print $20; found=1 } END { if (!found) exit 1 }'
}

process_name_matches() {
  wanted_pid=$1
  wanted_name=$2
  {
    ps -A -o PID,NAME 2>/dev/null
    ps_code=$?
    printf 'P3A28B_PS_STATUS %s\n' "$ps_code"
  } | awk -v wanted_pid="$wanted_pid" -v wanted_name="$wanted_name" '
    $1 == "P3A28B_PS_STATUS" { if (NF != 2 || $2 != "0") bad=1; saw_status=1; next }
    saw_status { bad=1; next }
    NR == 1 { if (toupper($1) != "PID" || toupper($2) != "NAME") bad=1; next }
    $1 == wanted_pid && $2 == wanted_name && NF == 2 { matched++ }
    END {
      if (bad || !saw_status) exit 3
      if (matched != 1) exit 1
    }
  '
}

emit_process_status() {
  pid_value=$1; name_value=$2; start_value=$3; code_value=$4
  reserve_record || return 1
  printf 'P3A28B\tPROCESS_STATUS\t%s\t%s\t%s\t%s\n' "$pid_value" "$name_value" "$start_value" "$code_value"
}

emit_fsstat() {
  library_path=$1
  stat_output=$(stat -c '%d %i' "$library_path" 2>/dev/null)
  stat_status=$?
  if [ "$stat_status" -eq 0 ] && printf '%s\n' "$stat_output" | awk 'NF == 2 && $1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ { ok=1 } END { exit !ok }'; then
    set -- $stat_output
    reserve_record || return 1
    printf 'P3A28B\tFSSTAT\t%s\tOBSERVED\t%s\t%s\n' "$library_path" "$1" "$2"
  else
    reserve_record || return 1
    printf 'P3A28B\tFSSTAT\t%s\tUNAVAILABLE\tSTAT_UNAVAILABLE\n' "$library_path"
  fi
}

printf 'P3A28B\tBEGIN\t1\n'
emit_fsstat '/vendor/lib64/camx_core.so' || stop_scan=1
emit_fsstat '/vendor/lib64/quickcamera.core.so' || stop_scan=1

candidate_output=$(
  {
    ps -A -o PID,NAME 2>/dev/null
    ps_code=$?
    printf 'P3A28B_PS_STATUS %s\n' "$ps_code"
  } | awk -v max="$MAX_PROCESSES" '
    $1 == "P3A28B_PS_STATUS" {
      if (NF != 2 || $2 != "0") ps_bad=1
      saw_ps_status=1
      next
    }
    saw_ps_status { bad=1; next }
    NR == 1 { if (toupper($1) != "PID" || toupper($2) != "NAME") bad=1; next }
    tolower($2) ~ /(quickcamera|pvr|hidl.*camera|camera.*hidl)/ {
      if (NF != 2 || $1 !~ /^[0-9]+$/ || length($1) > 10 || $2 !~ /^[A-Za-z0-9_.:@+-]+$/ || length($2) > 256) { bad=1; next }
      if (count >= max) { overflow=1; next }
      printf "%s %s\n", $1, $2
      count++
    }
    END {
      if (NR == 0 || !saw_ps_status) bad=1
      if (ps_bad) exit 5
      if (bad) exit 3
      if (overflow) exit 4
    }
  '
)
  candidate_status=$?
  if [ "$candidate_status" -eq 3 ]; then
    reserve_record && printf 'P3A28B\tGLOBAL_STATUS\tPROCESS_INVENTORY_MALFORMED\n'
    scan_status=BLOCKED_PROCESS_INVENTORY
    stop_scan=1
  elif [ "$candidate_status" -eq 4 ]; then
    reserve_record && printf 'P3A28B\tGLOBAL_STATUS\tPROCESS_LIMIT_REACHED\n'
    scan_status=PROCESS_LIMIT_REACHED
    stop_scan=1
  elif [ "$candidate_status" -eq 5 ]; then
    reserve_record && printf 'P3A28B\tGLOBAL_STATUS\tPROCESS_INVENTORY_UNAVAILABLE\n'
    scan_status=BLOCKED_PROCESS_INVENTORY
    stop_scan=1
  elif [ -z "$candidate_output" ]; then
    reserve_record && printf 'P3A28B\tGLOBAL_STATUS\tNO_MATCHING_PROCESSES\n'
    scan_status=NO_MATCHING_PROCESSES
    stop_scan=1
  else
    old_ifs=$IFS
    IFS=$NL
    for candidate in $candidate_output; do
      [ "$stop_scan" -eq 0 ] || break
      IFS=' '
      set -- $candidate
      pid_value=$1
      name_value=$2
      IFS=$NL

      start_before=$(read_starttime "$pid_value")
      start_status=$?
      if [ "$start_status" -ne 0 ] || [ -z "$start_before" ]; then
        if [ -d "$PROC_ROOT/$pid_value" ]; then
          emit_process_status "$pid_value" "$name_value" NOT_OBSERVED PROCESS_IDENTITY_UNAVAILABLE || break
          scan_status=PROCESS_IDENTITY_UNAVAILABLE
        else
          emit_process_status "$pid_value" "$name_value" NOT_OBSERVED PROCESS_EXITED || break
          scan_status=PROCESS_EXITED
        fi
        stop_scan=1; break
      fi
      process_name_matches "$pid_value" "$name_value"
      identity_status=$?
      if [ "$identity_status" -ne 0 ]; then
        if [ "$identity_status" -eq 1 ]; then
          emit_process_status "$pid_value" "$name_value" "$start_before" PROCESS_IDENTITY_CHANGED || break
          scan_status=PROCESS_IDENTITY_CHANGED
        else
          emit_process_status "$pid_value" "$name_value" "$start_before" PROCESS_IDENTITY_UNAVAILABLE || break
          scan_status=PROCESS_IDENTITY_UNAVAILABLE
        fi
        stop_scan=1; break
      fi

      remaining_records=$((MAX_RECORDS - record_count - 1))
      map_output=$(awk -v path1='/vendor/lib64/camx_core.so' -v path2='/vendor/lib64/quickcamera.core.so' \
        -v pid_value="$pid_value" -v name_value="$name_value" \
        -v start_value="$start_before" -v max_records="$remaining_records" '
        {
          wanted = ($6 == path1 || $6 == path2)
          if (!wanted) next
          if (!($1 ~ /^[0-9a-fA-F]+-[0-9a-fA-F]+$/) ||
              !($2 ~ /^[r-][w-][x-][ps]$/) ||
              !($3 ~ /^[0-9a-fA-F]+$/) ||
              !($4 ~ /^[0-9a-fA-F]+:[0-9a-fA-F]+$/) ||
              !($5 ~ /^[0-9]+$/)) { bad=1; next }
          path=$6
          if (NF == 7 && $7 == "(deleted)") path=path " (deleted)"
          else if (NF != 6) { bad=1; next }
          if (count >= max_records) { overflow=1; next }
          printf "P3A28B\tMAP\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", \
            pid_value, name_value, start_value, $1, $2, $3, $4, $5, path
          count++
        }
        END {
          if (bad) exit 7
          if (overflow) exit 8
        }
      ' "$PROC_ROOT/$pid_value/maps" 2>/dev/null)
      map_parse_status=$?
      start_after=$(read_starttime "$pid_value")
      after_status=$?
      if [ "$after_status" -ne 0 ] || [ -z "$start_after" ]; then
        if [ -d "$PROC_ROOT/$pid_value" ]; then
          emit_process_status "$pid_value" "$name_value" "$start_before" PROCESS_IDENTITY_UNAVAILABLE || break
          scan_status=PROCESS_IDENTITY_UNAVAILABLE
        else
          emit_process_status "$pid_value" "$name_value" "$start_before" PROCESS_EXITED || break
          scan_status=PROCESS_EXITED
        fi
        stop_scan=1; break
      fi
      if [ "$start_before" != "$start_after" ]; then
        emit_process_status "$pid_value" "$name_value" "$start_before" PID_REUSED || break
        scan_status=PID_REUSED; stop_scan=1; break
      fi
      process_name_matches "$pid_value" "$name_value"
      identity_status=$?
      if [ "$identity_status" -ne 0 ]; then
        if [ "$identity_status" -eq 1 ]; then
          emit_process_status "$pid_value" "$name_value" "$start_before" PROCESS_IDENTITY_CHANGED || break
          scan_status=PROCESS_IDENTITY_CHANGED
        else
          emit_process_status "$pid_value" "$name_value" "$start_before" PROCESS_IDENTITY_UNAVAILABLE || break
          scan_status=PROCESS_IDENTITY_UNAVAILABLE
        fi
        stop_scan=1; break
      fi
      if [ "$map_parse_status" -eq 7 ]; then
        emit_process_status "$pid_value" "$name_value" "$start_before" MALFORMED_MAPS || break
        scan_status=MALFORMED_MAPS; stop_scan=1; break
      elif [ "$map_parse_status" -ne 0 ] && [ "$map_parse_status" -ne 8 ]; then
        if [ -f "$PROC_ROOT/$pid_value/maps" ]; then
          emit_process_status "$pid_value" "$name_value" "$start_before" PROC_ACCESS_DENIED || break
          scan_status=PROC_ACCESS_DENIED
        else
          emit_process_status "$pid_value" "$name_value" "$start_before" PROC_MAPS_UNAVAILABLE || break
          scan_status=PROC_MAPS_UNAVAILABLE
        fi
        stop_scan=1; break
      fi
      if [ -z "$map_output" ] && [ "$map_parse_status" -eq 8 ]; then
        emit_process_status "$pid_value" "$name_value" "$start_before" RECORD_LIMIT_REACHED || break
        scan_status=LIMIT_REACHED; stop_scan=1; break
      fi
      if [ -z "$map_output" ]; then
        emit_process_status "$pid_value" "$name_value" "$start_before" NO_TARGET_MAPPING || break
        continue
      fi
      emit_process_status "$pid_value" "$name_value" "$start_before" MAPPED || break
      if [ -n "$map_output" ]; then
        map_count=$(printf '%s\n' "$map_output" | awk 'END { print NR }')
        printf '%s\n' "$map_output"
        record_count=$((record_count + map_count))
      else
        map_count=0
      fi
      if [ "$map_parse_status" -eq 8 ]; then
        scan_status=LIMIT_REACHED; stop_scan=1; break
      fi
    done
    IFS=$old_ifs
  fi

printf 'P3A28B\tEND\t%s\t%s\n' "$record_count" "$scan_status"
