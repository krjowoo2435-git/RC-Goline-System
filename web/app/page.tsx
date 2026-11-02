import RecordsBoard from "@/components/RecordsBoard";
import { readNotice } from "@/lib/notice";
import { readRecords } from "@/lib/records";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const [{ records }, { notice }] = await Promise.all([
    readRecords(),
    readNotice(),
  ]);
  return (
    <RecordsBoard
      initialRecords={records}
      initialNotice={notice.content}
    />
  );
}
