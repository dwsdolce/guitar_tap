rm -f WILY.txt
for i in *py
do
echo $i
wily report $i -f HTML -o reports/$i.html
done
wily rank
