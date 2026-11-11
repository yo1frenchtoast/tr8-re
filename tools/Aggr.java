// Ghidra pre-script: enable the ARM aggressive instruction finder (the application has
// many functions only reached through tables and vtables).
import ghidra.app.script.GhidraScript;
public class Aggr extends GhidraScript {
  public void run() throws Exception {
    setAnalysisOption(currentProgram, "ARM Aggressive Instruction Finder", "true");
  }
}
