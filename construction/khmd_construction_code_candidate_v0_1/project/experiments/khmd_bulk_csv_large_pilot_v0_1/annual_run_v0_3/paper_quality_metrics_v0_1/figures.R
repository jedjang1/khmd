args <- commandArgs(TRUE); stopifnot(length(args)==3L)
gate <- Sys.getenv('KHMD_R_START_GATE'); deadline <- Sys.time()+30
while(!file.exists(gate)) { if(Sys.time()>deadline) stop('ADMISSION_TIMEOUT'); Sys.sleep(.01) }
input <- args[1]; output <- args[2]; figure <- args[3]
stopifnot(figure %in% c('1','2'))
read_table <- function(name) read.csv(file.path(input,paste0(name,'.csv')),fileEncoding='UTF-8-BOM',stringsAsFactors=FALSE,na.strings='NA')
t <- proc.time()[['elapsed']]
yearly <- read_table('year_family'); regional <- read_table('region_year_family')
families <- c('SALE','RENT'); titles <- c('Apartment sales','Apartment leases (RENT)')
draw1 <- function() {
 par(mfrow=c(1,2),mar=c(4.3,4.5,3.0,0.8),oma=c(2.4,0,1,0),family='sans',las=1,cex=.9)
 ymax <- max(yearly$input_n)/1e6*1.16
 for(i in seq_along(families)) {
  d <- yearly[yearly$transaction_family==families[i],]; d <- d[order(d$year),]
  x <- barplot(rbind(d$assigned_n,d$unassigned_n)/1e6,beside=FALSE,col=c('#0072B2','#E69F00'),border=NA,ylim=c(0,ymax),axes=FALSE,space=.3)
  axis(2);axis(1,at=x,labels=d$year,las=2,cex.axis=.8,tick=FALSE);box(bty='l')
  lines(x,d$input_n/1e6,type='o',pch=16,cex=.4,lwd=1,col='#222222')
  title(titles[i],adj=0,font.main=2);mtext('Observation occurrences (millions)',2,line=3,las=0)
  legend('topleft',legend=c('Input (line)','Assigned','Unassigned'),col=c('#222222','#0072B2','#E69F00'),pch=c(16,15,15),pt.cex=c(.6,1.4,1.4),bty='n',cex=.78)
 }
 mtext('Calendar year of contract | input = assigned + unassigned; repeated occurrences retained',outer=TRUE,side=1,line=.6,cex=.8)
}
draw2 <- function() {
 palette <- colorRampPalette(c('#f7fbff','#c6dbef','#6baed6','#2171b5','#08306b'))(301)
 # Explicit common zoomed scale 85-100%, no clipping. Counts/rates remain exact in source CSV.
 stopifnot(all(is.na(regional$assignment_rate) | regional$assignment_rate>=.85))
 layout(matrix(c(1,2,3),1,3),widths=c(1,1,.12));par(oma=c(2.4,0,1.2,0),family='sans')
 regions <- sort(unique(regional$region_label)); years <- sort(unique(regional$year))
 stopifnot(all(grepl('^[ -~]+$',regions)))
 for(i in seq_along(families)) {
  par(mar=c(4.8,9.5,2.6,.7));plot(NA,xlim=c(.5,length(years)+.5),ylim=c(.5,length(regions)+.5),xaxs='i',yaxs='i',axes=FALSE,xlab='',ylab='')
  for(y in seq_along(regions)) for(x in seq_along(years)) {
   d <- regional[regional$region_label==regions[y] & regional$year==years[x] & regional$transaction_family==families[i],]
   stopifnot(nrow(d)<=1L);rate <- if(nrow(d)) d$assignment_rate*100 else NA_real_
   fill <- if(is.na(rate)) '#dddddd' else palette[max(1,min(301,floor((rate-85)*20)+1))]
   rect(x-.5,y-.5,x+.5,y+.5,col=fill,border='white',lwd=.4)
   text(x,y,if(is.na(rate)) 'NA' else sprintf('%.1f',rate),cex=.47,col=if(!is.na(rate)&&rate>=96) 'white' else '#222222')
  }
  axis(1,at=seq_along(years),labels=years,las=2,tick=FALSE,cex.axis=.72)
  axis(2,at=seq_along(regions),labels=regions,las=1,tick=FALSE,cex.axis=.72)
  title(titles[i],adj=0,cex.main=1.05)
 }
 par(mar=c(4.8,.3,2.6,2.8));plot(NA,xlim=c(0,1),ylim=c(85,100),axes=FALSE,xlab='',ylab='',xaxs='i',yaxs='i')
 for(k in 0:299) rect(0,85+k/20,1,85+(k+1)/20,col=palette[k+1],border=NA)
 axis(4,at=seq(85,100,5),las=1,cex.axis=.75);mtext('% assigned',3,line=.5,cex=.65)
 mtext('Query regions, not historical boundaries | summed assigned / summed input | common color scale: 85-100%',outer=TRUE,side=1,line=.7,cex=.8)
}
for(format in c('png','svg','pdf')) {
 path <- file.path(output,paste0('figure_',figure,'.',format));stopifnot(!file.exists(path))
 w <- if(figure=='1') 11.8 else 15; h <- if(figure=='1') 5.2 else 7.6
 if(format=='png') png(path,width=w,height=h,units='in',res=220,type='cairo')
 if(format=='svg') svg(path,width=w,height=h)
 if(format=='pdf') pdf(path,width=w,height=h,useDingbats=FALSE)
 if(figure=='1') draw1() else draw2()
 dev.off();gc()
}
write.csv(data.frame(status='PASS',figure=figure,elapsed_seconds=proc.time()[['elapsed']]-t),file.path(output,'execution.csv'),row.names=FALSE)
cat('FIGURE_COMPLETE',figure,'\n')
