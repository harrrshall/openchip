module tb;
reg clk=0, reset=0, data=0, ack=0;
wire [3:0] count;
wire counting, done;
integer samples=0, mismatches=0, ack_mismatches=0;
integer payload,bitnum,elapsed,remain,holdcycle;
TopModule dut(.clk(clk),.reset(reset),.data(data),.count(count),.counting(counting),.done(done),.ack(ack));
task tick;
input r,d,a;
begin
 clk=0; reset=r;data=d;ack=a;#5;clk=1;#5;
end
endtask
task check;
input ec,ed;
input integer ev;
begin
 samples=samples+1;
 if(counting!==ec || done!==ed || (ec && count!==ev[3:0])) begin
  mismatches=mismatches+1;
  if(mismatches<25) $display("MISMATCH payload=%0d elapsed=%0d got=%b,%b,%d expected=%b,%b,%0d ack=%b",payload,elapsed,counting,done,count,ec,ed,ev,ack);
 end
end
endtask
initial begin
 tick(1,0,0);check(0,0,0);
 for(payload=0;payload<16;payload=payload+1) begin
  // Consecutive transactions, no reset between them.
  tick(0,1,0);check(0,0,0);
  tick(0,1,0);check(0,0,0);
  tick(0,0,0);check(0,0,0);
  tick(0,1,0);check(0,0,0);
  for(bitnum=3;bitnum>=0;bitnum=bitnum-1) begin
   tick(0,(payload>>bitnum)&1,0);
   if(bitnum==0) check(1,0,payload);else check(0,0,0);
  end
  for(elapsed=1;elapsed<=(payload+1)*1000;elapsed=elapsed+1) begin
   tick(0,elapsed%2,elapsed%3==0);
   remain=payload-elapsed/1000;
   if(elapsed==(payload+1)*1000) check(0,1,0);else check(1,0,remain);
  end
  for(holdcycle=0;holdcycle<3;holdcycle=holdcycle+1) begin tick(0,1,0);check(0,1,0);end
  tick(0,0,1);
  if(done!==0) ack_mismatches=ack_mismatches+1;
  check(0,0,0);
 end
 $display("SERIAL_TIMER_RESULT mismatches=%0d samples=%0d ack_mismatches=%0d",mismatches,samples,ack_mismatches);
 $finish;
end
endmodule
