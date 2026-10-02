-- Synthetic appointments database. ticks: one row per second from the writer; the ground truth for data loss.
CREATE DATABASE appointments ON (NAME = N'appointments', FILENAME = N'/var/opt/mssql/data/appointments.mdf')
LOG ON (NAME = N'appointments_log', FILENAME = N'/var/opt/mssql/data/appointments_log.ldf');
GO
ALTER DATABASE appointments SET RECOVERY FULL;
GO
USE appointments;
CREATE TABLE dbo.ticks (seq bigint IDENTITY(1, 1) PRIMARY KEY, written_at datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME());
CREATE TABLE dbo.appointment (id int IDENTITY PRIMARY KEY, patient_code char(8) NOT NULL, starts_at datetime2(0) NOT NULL);
INSERT dbo.appointment (patient_code, starts_at)
SELECT TOP (500) CONCAT('P', RIGHT('0000000' + CAST(ROW_NUMBER() OVER (ORDER BY (SELECT 1)) AS varchar(7)), 7)),
       DATEADD(hour, ROW_NUMBER() OVER (ORDER BY (SELECT 1)), '2026-10-05T08:00:00')
FROM sys.all_objects;
GO
