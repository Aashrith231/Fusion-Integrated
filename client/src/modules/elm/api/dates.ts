/** Calendar-date helpers for the ELM module.
 *
 *  `DateInput` hands back a `Date` at *local* midnight. Serialising it
 *  with `toISOString().slice(0, 10)` shifts the day one back for every
 *  UTC+ timezone (IST midnight → 18:30 the previous day UTC), so every
 *  wire date must be formatted in local time instead.
 */
import dayjs from "dayjs";

export function isoDate(d: Date | null): string | null {
  return d ? dayjs(d).format("YYYY-MM-DD") : null;
}
