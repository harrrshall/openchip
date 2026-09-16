module tb;
reg clk=0,load=0; reg [9:0] data=0; wire tc;
integer expected=0,known=0,mismatches=0,samples=0,a,b;
TopModule dut(.clk(clk),.load(load),.data(data),.tc(tc));
task check;
begin
 samples=samples+1;
 if(tc !== (expected==0)) begin
  mismatches=mismatches+1;
  if(mismatches<8)$display("TIMER mismatch sample=%0d load=%b data=%0d expected_count=%0d tc=%b",samples,load,data,expected,tc);
 end
end
endtask
task tick;
input l;input [9:0] value;
begin
 clk=0;load=l;data=value;#5;
 if(known)check;
 if(l)expected=value;else if(expected>0)expected=expected-1;
 clk=1;#1;known=1;check;#4;clk=0;
end
endtask
initial begin
 for(a=0;a<1024;a=a+1)begin
  tick(1,a);
  for(b=0;b<a+3;b=b+1)tick(0,0);
 end
 for(a=0;a<1024;a=a+1)begin
  tick(1,1023);tick(0,0);tick(1,a);tick(0,0);
 end
 $display("TIMER_RESULT mismatches=%0d samples=%0d",mismatches,samples);
 if(mismatches)$fatal(1,"timer mismatch");$finish;
end
endmodule
