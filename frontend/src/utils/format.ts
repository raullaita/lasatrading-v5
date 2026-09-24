const pad2 = (n: number): string => n.toString().padStart(2, "0");

function toDate(input: string | Date): Date {
  if (typeof input !== "string") return input;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(input);
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }
  return new Date(input);
}

export function formatDateEs(input: string | Date): string {
  const d = toDate(input);
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
}

export function formatDateTimeEs(input: string | Date): string {
  const d = toDate(input);
  return `${formatDateEs(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}