import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Kept despite having no callers today: components.json points shadcn's
 * `utils` alias here, so anything added with `npx shadcn add` will import
 * `cn` from this file and fail to build without it.
 *
 * formatCurrency() used to sit alongside it and has been removed. It had
 * no callers either, and unlike `cn` nothing would ever generate one - it
 * was a second money formatter competing with gbp() in page.tsx and
 * payrollMessage.ts, taking a `number` where every figure from the API
 * arrives as a decimal string. The way to get money formatting wrong here
 * is to have two of them and reach for the one that parses to a float.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}