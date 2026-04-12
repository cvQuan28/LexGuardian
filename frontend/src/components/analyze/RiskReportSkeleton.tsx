export function RiskReportSkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      {/* Scorecard skeleton */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-gray-100" />
            <div className="space-y-2">
              <div className="h-3 w-20 rounded bg-gray-100" />
              <div className="h-4 w-48 rounded bg-gray-200" />
            </div>
          </div>
          <div className="h-6 w-24 rounded-full bg-gray-200" />
        </div>
        <div className="grid grid-cols-3 gap-4 pt-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col items-center gap-1">
              <div className="h-8 w-10 rounded bg-gray-100" />
              <div className="h-3 w-16 rounded bg-gray-100" />
            </div>
          ))}
        </div>
        <div className="space-y-2 pt-2 border-t border-gray-50">
          <div className="h-3 w-full rounded bg-gray-100" />
          <div className="h-3 w-5/6 rounded bg-gray-100" />
          <div className="h-3 w-4/6 rounded bg-gray-100" />
        </div>
      </div>

      {/* Risk items skeleton */}
      <div className="space-y-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-100 p-4">
            <div className="flex items-center gap-3">
              <div className="h-5 w-16 rounded-full bg-gray-100" />
              <div className="flex-1 space-y-1.5">
                <div className="h-4 w-36 rounded bg-gray-200" />
                <div className="h-3 w-24 rounded bg-gray-100" />
              </div>
              <div className="h-4 w-4 rounded bg-gray-100" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
