import type { GitAuthMethod } from "../types/api";

const SSH_GIT_URL_RE = /^[^@]+@[^:]+:.+/;
const IMAGE_TAG_RE = /^[a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+$/;
const BLOCKED_IMAGE_TAGS = new Set(["latest", "stable", "edge"]);

function hasProtocol(value: string, protocol: string): boolean {
  try {
    return new URL(value).protocol === protocol;
  } catch {
    return false;
  }
}

export function isHttpsGitUrl(value: string): boolean {
  return hasProtocol(value, "https:");
}

export function isSshGitUrl(value: string): boolean {
  return hasProtocol(value, "ssh:") || SSH_GIT_URL_RE.test(value);
}

export function isGitUrl(value: string): boolean {
  return isHttpsGitUrl(value) || isSshGitUrl(value);
}

export function isGitUrlAllowedForAuth(value: string, authMethod: GitAuthMethod): boolean {
  if (authMethod === "token") return isHttpsGitUrl(value);
  if (authMethod === "ssh_key") return isSshGitUrl(value);
  return isGitUrl(value);
}

export function isPinnedDockerImage(value: string): boolean {
  if (!IMAGE_TAG_RE.test(value)) return false;
  const imageTag = value.slice(value.lastIndexOf(":") + 1);
  return !BLOCKED_IMAGE_TAGS.has(imageTag.toLowerCase());
}
