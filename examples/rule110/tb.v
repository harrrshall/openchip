module tb;
reg clk=0,load=0;reg [511:0] data=0;wire [511:0] q;reg [511:0] expected=0,next_q;integer n,i,errors=0;reg [31:0] rng=32'h19ca753b;
TopModule dut(.clk(clk),.load(load),.data(data),.q(q));always #5 clk=~clk;
initial begin
 for(n=0;n<4096;n=n+1)begin
  @(negedge clk);load=(n%17==0);
  for(i=0;i<512;i=i+1)begin rng=(rng<<1)^((rng[31])?32'h04c11db7:32'h0);data[i]=rng[0];end
  if(load)expected=data;else begin
   for(i=0;i<512;i=i+1)next_q[i]=(expected[i] | ((i==0)?1'b0:expected[i-1])) & ~(((i==511)?1'b0:expected[i+1]) & expected[i] & ((i==0)?1'b0:expected[i-1]));
   expected=next_q;
  end
  @(posedge clk);#1;if(q !== expected)errors=errors+1;
 end
 $display("CELL_RESULT mismatches=%0d samples=4096",errors);$finish;
end
endmodule
