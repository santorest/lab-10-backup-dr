SET NOCOUNT ON;
SELECT CONCAT(CONVERT(varchar(23), MAX(written_at), 126), 'Z'), COUNT_BIG(*), MIN(seq), MAX(seq) FROM appointments.dbo.ticks;
