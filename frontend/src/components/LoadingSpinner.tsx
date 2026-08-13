export function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-border-default border-t-analytic" />
    </div>
  )
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-negative/40 bg-negative-dim px-4 py-3 text-sm text-negative">
      Failed to load: {message}
    </div>
  )
}
