SELECT to_char(max(written_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), count(*), min(seq), max(seq) FROM ticks;
