export function DurationDisplay({ seconds }: { seconds: number | null | undefined }) {
  if (seconds === null || seconds === undefined) return <span>-</span>;
  
  if (seconds < 60) {
    return <span>{Math.round(seconds)}s</span>;
  }
  
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  
  return (
    <span>
      {minutes}m {remainingSeconds}s
    </span>
  );
}
