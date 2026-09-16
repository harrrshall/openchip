module tb;
reg clk=0,load=0;reg[9:0]data=0;wire tc;
integer expected=0,checks=0,errors=0,n,k;
reloadable_timer dut(.clk(clk),.load(load),.data(data),.tc(tc));always #5 clk=~clk;
task cycle;input integer l,d;begin
 @(negedge clk);load=l;data=d;
 if(l)expected=d;else if(expected>0)expected=expected-1;
 @(posedge clk);#1;checks=checks+1;if(tc!==(expected==0))errors=errors+1;
end endtask
initial begin
 for(n=0;n<1024;n=n+1)begin cycle(1,n);for(k=0;k<n+2;k=k+1)cycle(0,0);end
 cycle(1,1023);cycle(0,0);cycle(1,2);cycle(0,0);cycle(1,1);cycle(0,0);
 cycle(1,0);cycle(0,0);cycle(1,7);cycle(1,0);
 $display("TIMER_RESULT mismatches=%0d samples=%0d",errors,checks);$finish;
end
endmodule
