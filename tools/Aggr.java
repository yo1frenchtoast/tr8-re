import ghidra.app.script.GhidraScript;
public class Aggr extends GhidraScript {
  public void run() throws Exception {
    setAnalysisOption(currentProgram, "ARM Aggressive Instruction Finder", "true");
  }
}
