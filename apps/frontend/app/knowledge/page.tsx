import { Screen } from "@/components/layout/Screen";
import { PhasePlaceholder } from "@/components/ui/PhasePlaceholder";

export default function Page() {
  return (
    <Screen title="Knowledge">
      <PhasePlaceholder
        phase={7}
        title="Warehouse knowledge assistant"
        items={["Question box", "Answer with cited source cards", "Retrieved passage viewer"]}
      />
    </Screen>
  );
}
