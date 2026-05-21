import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import type { PaginatedResponse } from "../types/api"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function unwrapPaginated<T>(value: T[] | PaginatedResponse<T>): T[] {
  return Array.isArray(value) ? value : value.data;
}
