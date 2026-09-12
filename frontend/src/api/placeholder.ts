/**
 * `placeholderData` that keeps the previous result on screen while a new one
 * loads, but only when the previous query belongs to the same subject.
 *
 * Plain `keepPreviousData` would also carry fund A's rows over to fund B while
 * B loads, which reads as B's data. Pass the leading query-key parts that must
 * match (e.g. `["fund-snapshot", fund, accession]`): a filter or slider change
 * keeps the old rows visible, a change of fund shows the loading state.
 */
export function keepPreviousWithin(prefix: readonly unknown[]) {
  return <T>(
    previousData: T | undefined,
    previousQuery: { queryKey: readonly unknown[] } | undefined,
  ): T | undefined => {
    if (!previousQuery) return undefined;
    const sameSubject = prefix.every((part, index) => previousQuery.queryKey[index] === part);
    return sameSubject ? previousData : undefined;
  };
}
