import RecordsBoard from "@/components/RecordsBoard";
import { readRecords } from "@/lib/records";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { records } = await readRecords();
  return <RecordsBoard initialRecords={records} />;
}
