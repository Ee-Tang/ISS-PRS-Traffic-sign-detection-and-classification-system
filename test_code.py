import numpy as np
import tensorflow as tf

a = tf.constant([[ 309.0583 ,   133.32974 ,  399.178 ,    235.31738 ],
 [ 297.79614,   911.13464,   407.89258,  1080.4592  ],
 [ 267.1739  ,  195.6159  ,  385.0858  ,  348.8131  ],
 [ 287.71014  , 843.6184   , 381.99927  , 972.5736  ],
 [ 311.98575   ,364.53888   ,363.37512   ,441.15137 ],
 [ 261.93262    ,-1.438632,  499.62122,   157.29613 ],
 [ 312.02383  , 508.2111   , 358.61963 ,  559.07605 ],
 [  15.33833  , 554.62256   ,441.61197  , 838.222   ],
 [ 277.2813   ,1014.2731    ,436.0408   ,1231.3616  ]])
const = tf.ones([a.shape.as_list()[0],1])*5
print(tf.concat([a,const], axis = 1))