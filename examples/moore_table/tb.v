module tb;
reg clk=0,reset=0,in=0;wire out;TopModule dut(clk,reset,in,out);
integer expected=0,mismatches=0,samples=0,pattern,k;integer transitions[0:7];
task step;input rst;input bit_in;begin
 clk=0;reset=rst;in=bit_in;#2;clk=1;
 if(rst)expected=0;else expected=transitions[expected*2+bit_in];
 #2;samples=samples+1;if(out !== (expected==3))mismatches=mismatches+1;
 clk=0;#2;samples=samples+1;if(out !== (expected==3))mismatches=mismatches+1;
end endtask
initial begin
 transitions[0]=0;transitions[1]=1;transitions[2]=2;transitions[3]=1;
 transitions[4]=0;transitions[5]=3;transitions[6]=2;transitions[7]=1;
 for(pattern=0;pattern<256;pattern=pattern+1)begin
  step(1,pattern&1);
  for(k=0;k<8;k=k+1)step(0,(pattern>>k)&1);
  step(1,1);step(0,0);
 end
 $display("MOORE_RESULT mismatches=%0d samples=%0d",mismatches,samples);
 if(mismatches)$fatal(1,"Moore table mismatch");$finish;
end
endmodule
