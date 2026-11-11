// Ghidra post-script: write <out>.strings (defined strings with references) and <out>.c
// (decompiled C of every function). Argument: output path prefix.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.data.*;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import java.io.*;
public class DumpAll extends GhidraScript {
  public void run() throws Exception {
    String out = getScriptArgs()[0];
    PrintWriter pw = new PrintWriter(new FileWriter(out + ".c"));
    PrintWriter sw = new PrintWriter(new FileWriter(out + ".strings"));
    for (Data d : currentProgram.getListing().getDefinedData(true)) {
      if (d.hasStringValue()) {
        StringBuilder refs = new StringBuilder();
        for (Reference r : getReferencesTo(d.getAddress())) {
          Function f = getFunctionContaining(r.getFromAddress());
          refs.append(" ").append(r.getFromAddress()).append(f!=null?"("+f.getName()+")":"");
        }
        sw.println(d.getAddress()+"\t"+d.getValue()+"\t<-"+refs);
      }
    }
    sw.close();
    DecompInterface di = new DecompInterface();
    di.openProgram(currentProgram);
    for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
      DecompileResults r = di.decompileFunction(f, 60, monitor);
      pw.println("//==== " + f.getName() + " @ " + f.getEntryPoint());
      if (r != null && r.decompileCompleted()) pw.println(r.getDecompiledFunction().getC());
      else pw.println("// decompile failed");
    }
    pw.close();
  }
}
