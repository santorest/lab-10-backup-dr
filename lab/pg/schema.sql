-- Synthetic billing database. ticks: one row per second from the writer; the ground truth for data loss.
CREATE TABLE ticks (seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, written_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE invoice (id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, patient_code char(8) NOT NULL, amount numeric(10, 2) NOT NULL);
INSERT INTO invoice (patient_code, amount)
SELECT 'P' || lpad(n::text, 7, '0'), round((20 + random() * 180)::numeric, 2) FROM generate_series(1, 500) AS n;
