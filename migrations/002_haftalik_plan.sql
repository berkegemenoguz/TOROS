-- 002: Haftalik plan
-- Teslimatlarin bir haftalik takvime dagitilmasi icin iki kolon:
--   planlanan_gun : teslimatin planlandigi gun (rota o gun cikar, bu sadece dagilim)
--   kesinlesmis   : plan kilidi; TRUE ise haftalik plan bu teslimata DOKUNMAZ
-- arac_id aynen kalir: plan != sevkiyat. planlanan_gun = "hangi gun",
-- arac_id = "o gun gercekten rotaya girdi".

ALTER TABLE teslimatlar ADD COLUMN IF NOT EXISTS planlanan_gun DATE;
ALTER TABLE teslimatlar ADD COLUMN IF NOT EXISTS kesinlesmis BOOLEAN NOT NULL DEFAULT FALSE;
